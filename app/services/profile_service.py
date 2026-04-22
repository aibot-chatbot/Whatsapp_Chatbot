import json
import os


PROFILES_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "profiles_data.json")
)


def get_profiles():
    if not os.path.exists(PROFILES_FILE):
        return []

    with open(PROFILES_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def get_profile_by_name(profile_name):
    profiles = get_profiles()

    for profile in profiles:
        if profile.get("name") == profile_name:
            return profile

    return None


def save_profile(profile_data):
    profiles = get_profiles()

    profile_name = profile_data.get("name", "").strip()
    if not profile_name:
        raise ValueError("Profile name is required")

    profiles = [profile for profile in profiles if profile.get("name") != profile_name]
    profiles.append(profile_data)

    with open(PROFILES_FILE, "w", encoding="utf-8") as file:
        json.dump(profiles, file, indent=4, ensure_ascii=False)

    return profile_data

def delete_profile(profile_name):
    profiles = get_profiles()

    target_profile = None
    remaining_profiles = []

    for profile in profiles:
        if profile.get("name") == profile_name:
            target_profile = profile
        else:
            remaining_profiles.append(profile)

    if not target_profile:
        raise ValueError("Profile not found")

    with open(PROFILES_FILE, "w", encoding="utf-8") as file:
        json.dump(remaining_profiles, file, indent=4, ensure_ascii=False)

    return target_profile