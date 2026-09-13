import requests
import json
from typing import Optional, Dict, Any

# --- Configuration ---
# Primary Repository Owner (Organization)
OWNER = "DarkFlippers"
# Repository Name
REPO_NAME = "unleashed-firmware"
# Default branch to track (unleashed-firmware uses 'dev')
BRANCH = "dev"
# GitHub API Endpoint for the latest commit on the default branch.
# This bypasses the release tagging system and returns the absolute latest
# commit SHA, guaranteeing every line of code written since the last tag.
API_URL = f"https://api.github.com/repos/{OWNER}/{REPO_NAME}/commits/{BRANCH}"

def fetch_latest_firmware_info(owner: str, repo_name: str, api_url: str) -> Optional[Dict[str, Any]]:
    """
    Fetches the latest commit information from the GitHub API endpoint.

    Args:
        owner: The owner/organization name (e.g., 'flipperdevices').
        repo_name: The repository name (e.g., 'nespricer').
        api_url: The full URL to the commits/{branch} endpoint.

    Returns:
        A dictionary containing commit data, or None if fetching fails.
    """
    print(f"[*] Connecting to GitHub API for {owner}/{repo_name} (latest commit)...")
    try:
        # Making the GET request to the GitHub API
        response = requests.get(api_url)
        response.raise_for_status()  # Raises an HTTPError for bad responses (4xx or 5xx)

        data = response.json()
        print("[+] Successfully retrieved latest commit data.")
        return data

    except requests.exceptions.HTTPError as e:
        print(f"[ERROR] HTTP Error occurred while fetching data: {e}")
        if 'response' in locals():
            print(f"  Status Code: {response.status_code}")
            try:
                error_details = response.json()
                print(f"  API Message: {error_details.get('message', 'No specific message provided.')}")
            except json.JSONDecodeError:
                 print("  Could not decode error response body.")

    except requests.exceptions.RequestException as e:
        # Catches connection errors, timeouts, DNS failures, etc.
        print(f"[ERROR] A general Request Error occurred: {e}")

    return None

def extract_firmware_details(commit_data: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """
    Extracts the commit SHA (used as the version string) and constructs a
    source-archive download link from the latest commit data.

    Args:
        commit_data: The dictionary returned by fetch_latest_firmware_info.

    Returns:
        A dictionary containing 'version' and 'download_url', or None if extraction fails.
    """
    try:
        # 1. Extract the full 40-character commit SHA as the Version String.
        version = commit_data.get("sha")
        if not version:
            raise KeyError("Missing 'sha' in the commit data.")

        # 2. Construct a source-archive URL for the commit. The /commits/{ref}
        #    endpoint does not expose release assets, so we build a codeload
        #    ZIP URL pinned to this exact SHA.
        download_url = f"https://github.com/{OWNER}/{REPO_NAME}/archive/{version}.zip"

        return {
            "version": version,
            "download_url": download_url,
        }

    except (KeyError, IndexError) as e:
        print(f"[CRITICAL EXTRACTION ERROR] Failed to extract required details from commit data. Reason: {e}")
        return None


def main():
    """
    Main execution function to run the fetching and extraction process.
    """
    # 1. Fetch Data
    commit_data = fetch_latest_firmware_info(OWNER, REPO_NAME, API_URL)

    if commit_data:
        # 2. Extract Details
        details = extract_firmware_details(commit_data)

        if details:
            print("\n" + "="*60)
            print("FLIPPER ZERO FIRMWARE AUTOMATION COMPLETE")
            print("="*60)
            print(f"LATEST COMMIT SHA (Version String): {details['version']}")
            print("-" * 60)
            print("DIRECT SOURCE DOWNLOAD URL:")
            print(details['download_url'])
            print("="*60)
            print("\nACTION REQUIRED: Use the Commit SHA as the version identifier, or use the URL to download the source archive pinned to this commit.")
        else:
            print("\n[FAILURE] Script finished but could not extract usable commit details.")
    else:
        print("\n[FAILURE] Script finished because failed to retrieve data from GitHub API.")

if __name__ == "__main__":
    # Ensure requests library is installed: pip install requests
    main()
