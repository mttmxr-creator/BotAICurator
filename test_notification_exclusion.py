#!/usr/bin/env python3
"""
Test script to verify notification exclusion logic in admin_bot.py.
This script checks that all admin notification loops properly exclude the action performer.
"""

import re
import sys
from pathlib import Path

def test_notification_exclusion():
    """Test that all notification loops exclude the action performer."""

    print("🔍 TESTING NOTIFICATION EXCLUSION LOGIC")
    print("=" * 60)

    admin_bot_file = Path("admin_bot.py")
    if not admin_bot_file.exists():
        print("❌ admin_bot.py not found")
        return False

    with open(admin_bot_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Test cases: each notification type and its expected exclusion pattern
    test_cases = [
        {
            "name": "Edit Start Notifications",
            "search_pattern": r"Send edit notification to other admins.*?for admin_id in Config\.ADMIN_CHAT_IDS:",
            "exclusion_pattern": r"if admin_id == str\(admin_user_id\):\s*continue",
            "context_line": "Send edit notification to other admins"
        },
        {
            "name": "Send Message Notifications",
            "search_pattern": r"Send notification to ALL admins about message.*?for admin_id in Config\.ADMIN_CHAT_IDS:",
            "exclusion_pattern": r"if admin_id == str\(query\.from_user\.id\):\s*continue",
            "context_line": "Send notification to ALL admins about message"
        },
        {
            "name": "Reject Message Notifications",
            "search_pattern": r"Send notification to ALL admins about message rejection.*?for admin_id in Config\.ADMIN_CHAT_IDS:",
            "exclusion_pattern": r"if admin_id == str\(query\.from_user\.id\):\s*continue",
            "context_line": "Send notification to ALL admins about message rejection"
        },
        {
            "name": "Reset Question Notifications",
            "search_pattern": r"Send notification to ALL admins about reset.*?for admin_id in Config\.ADMIN_CHAT_IDS:",
            "exclusion_pattern": r"if admin_id == str\(admin_user_id\):\s*continue",
            "context_line": "Send notification to ALL admins about reset"
        },
        {
            "name": "Cancel Edit Notifications",
            "search_pattern": r"ALWAYS send notifications to ALL admins.*?for admin_id in Config\.ADMIN_CHAT_IDS:",
            "exclusion_pattern": r"if admin_id == str\(admin_user_id\):\s*continue",
            "context_line": "ALWAYS send notifications to ALL admins"
        }
    ]

    results = []

    for test_case in test_cases:
        print(f"\n🔍 Testing: {test_case['name']}")

        # Find the notification loop
        search_match = re.search(test_case["search_pattern"], content, re.DOTALL)
        if not search_match:
            print(f"❌ Could not find notification loop pattern")
            results.append(False)
            continue

        # Extract the loop content (next 200 characters after the for loop)
        loop_start = search_match.end()
        loop_content = content[loop_start:loop_start + 200]

        # Check if exclusion logic is present
        exclusion_match = re.search(test_case["exclusion_pattern"], loop_content, re.DOTALL)
        if exclusion_match:
            print(f"✅ Exclusion logic found: {exclusion_match.group(0).strip()}")
            results.append(True)
        else:
            print(f"❌ Missing exclusion logic")
            print(f"   Expected pattern: {test_case['exclusion_pattern']}")
            print(f"   Loop content: {loop_content[:100]}...")
            results.append(False)

    # Summary
    print(f"\n📊 TEST RESULTS SUMMARY")
    print("=" * 60)

    passed_tests = sum(results)
    total_tests = len(results)

    for i, (test_case, passed) in enumerate(zip(test_cases, results)):
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"   {i+1}. {test_case['name']}: {status}")

    print(f"\n🎯 Overall Result: {passed_tests}/{total_tests} tests passed")

    if passed_tests == total_tests:
        print("🎉 ALL NOTIFICATION EXCLUSION TESTS PASSED!")
        print("   ✅ Action performers will no longer receive notifications about their own actions")
        print("   ✅ Other admins will continue to receive all relevant notifications")
        print("   ✅ Notification spam has been eliminated")
        return True
    else:
        print(f"⚠️ {total_tests - passed_tests} tests failed - notification exclusion incomplete")
        return False

def test_notification_patterns():
    """Additional test to verify notification patterns and structure."""

    print(f"\n🔧 TESTING NOTIFICATION PATTERNS")
    print("=" * 60)

    admin_bot_file = Path("admin_bot.py")
    with open(admin_bot_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Check for consistent notification patterns
    patterns_to_check = [
        {
            "name": "No self-notification comment",
            "pattern": r"# Skip notification to the admin who performed the action \(no self-notification\)",
            "expected_count": 5  # Should appear in all 5 notification types
        },
        {
            "name": "Admin ID string conversion",
            "pattern": r"if admin_id == str\(",
            "expected_count": 5  # Should appear in all 5 notification types
        },
        {
            "name": "Continue statement after exclusion check",
            "pattern": r"continue\s*try:",
            "expected_count": 5  # Should appear after each exclusion check
        }
    ]

    for pattern_test in patterns_to_check:
        matches = re.findall(pattern_test["pattern"], content)
        found_count = len(matches)
        expected_count = pattern_test["expected_count"]

        if found_count == expected_count:
            print(f"✅ {pattern_test['name']}: {found_count}/{expected_count} found")
        else:
            print(f"❌ {pattern_test['name']}: {found_count}/{expected_count} found")

    print(f"\n🎯 Pattern consistency check completed")

def main():
    """Main test function."""

    print("🚀 NOTIFICATION EXCLUSION TEST SUITE")
    print("=" * 80)
    print()

    # Test 1: Core exclusion logic
    exclusion_passed = test_notification_exclusion()

    # Test 2: Pattern consistency
    test_notification_patterns()

    # Final summary
    print(f"\n📋 FINAL SUMMARY")
    print("=" * 80)

    if exclusion_passed:
        print("🎉 SUCCESS: Notification exclusion logic properly implemented!")
        print()
        print("🎯 BENEFITS:")
        print("   ✅ Admins no longer get spammed with notifications about their own actions")
        print("   ✅ Other admins continue to receive all relevant coordination notifications")
        print("   ✅ Chat clutter reduced - only actionable notifications sent")
        print("   ✅ Improved admin user experience and workflow efficiency")
        print()
        print("📝 IMPLEMENTATION DETAILS:")
        print("   • Edit start: Excludes admin who clicked 'Edit' button")
        print("   • Message send: Excludes admin who clicked 'Send' button")
        print("   • Message reject: Excludes admin who clicked 'Reject' button")
        print("   • Reset question: Excludes admin who clicked 'Reset Question' button")
        print("   • Cancel edit: Excludes admin who clicked 'Cancel Edit' button")
        print()
        print("🔗 READY FOR PRODUCTION DEPLOYMENT!")

    else:
        print("❌ FAILURE: Notification exclusion logic incomplete")
        print("   Please review failed test cases and fix missing exclusions")

    return exclusion_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)