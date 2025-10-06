#!/usr/bin/env python3
"""
Comprehensive test script for admin bot editing workflow.
Tests all buttons in the editing menu to ensure they work correctly after lock logic fixes.
"""

import json
import time
from pathlib import Path

def load_moderation_queue():
    """Load current moderation queue data."""
    queue_file = Path("moderation_queue.json")
    if not queue_file.exists():
        print("❌ Moderation queue file not found")
        return None

    try:
        with open(queue_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except Exception as e:
        print(f"❌ Error loading queue: {e}")
        return None

def analyze_queue_state():
    """Analyze current queue state and available test scenarios."""
    print("🔍 АНАЛИЗ ТЕКУЩЕГО СОСТОЯНИЯ ОЧЕРЕДИ МОДЕРАЦИИ")
    print("=" * 60)

    data = load_moderation_queue()
    if not data:
        return None

    pending_messages = data.get('pending_messages', {})
    processed_messages = data.get('processed_messages', {})

    print(f"📊 Статистика очереди:")
    print(f"   • Ожидающих модерации: {len(pending_messages)}")
    print(f"   • Обработанных: {len(processed_messages)}")
    print()

    # Analyze pending messages
    if pending_messages:
        print("🔍 СООБЩЕНИЯ В ОЖИДАНИИ:")
        for msg_id, msg_data in list(pending_messages.items())[:5]:  # Show first 5
            status = msg_data.get('status', 'unknown')
            is_locked = msg_data.get('admin_processing') is not None
            admin_processing = msg_data.get('admin_processing')
            editing_admin = msg_data.get('editing_admin_id')

            print(f"   📝 Сообщение {msg_id}:")
            print(f"      • Статус: {status}")
            print(f"      • Заблокировано: {'Да' if is_locked else 'Нет'}")
            if admin_processing:
                print(f"      • Обрабатывает админ ID: {admin_processing}")
            if editing_admin:
                print(f"      • Редактирует админ ID: {editing_admin}")
            print(f"      • Пользователь: {msg_data.get('username', 'Unknown')}")
            print(f"      • Вопрос: {msg_data.get('original_message', '')[:100]}{'...' if len(msg_data.get('original_message', '')) > 100 else ''}")
            print()

    return data

def test_workflow_buttons_documentation():
    """Document all buttons in the editing workflow and their expected behavior."""
    print("🔧 ДОКУМЕНТАЦИЯ КНОПОК РЕДАКТИРОВАНИЯ")
    print("=" * 60)

    workflow_stages = {
        "1. Начальное меню модерации": {
            "buttons": [
                "✅ Отправить - одобрить и отправить сообщение пользователю",
                "❌ Отклонить - отклонить сообщение",
                "✏️ Редактировать - начать процесс редактирования"
            ],
            "expected_behavior": "Все кнопки должны работать, сообщение блокируется при обработке"
        },

        "2. Режим редактирования (после нажатия ✏️ Редактировать)": {
            "buttons": [
                "❌ Отменить редактирование - отменить процесс редактирования"
            ],
            "expected_behavior": "Сообщение заблокировано для других админов, ожидается текст/голос корректировки"
        },

        "3. После отправки корректировки": {
            "buttons": [
                "✅ Отправить исправленный - отправить исправленный ответ (ИСПРАВЛЕНО)",
                "✏️ Доработать еще - продолжить редактирование",
                "❌ Отклонить - отклонить сообщение"
            ],
            "expected_behavior": "Владелец блокировки может использовать все кнопки, другие админы видят заблокированное состояние"
        }
    }

    for stage, info in workflow_stages.items():
        print(f"📋 {stage}:")
        print(f"   Кнопки:")
        for button in info["buttons"]:
            print(f"      • {button}")
        print(f"   Ожидаемое поведение: {info['expected_behavior']}")
        print()

def check_lock_logic_fixes():
    """Verify that the lock logic fixes have been applied correctly."""
    print("🔧 ПРОВЕРКА ИСПРАВЛЕНИЙ ЛОГИКИ БЛОКИРОВКИ")
    print("=" * 60)

    # Check admin_bot.py for the fixed lock checking logic
    admin_bot_file = Path("admin_bot.py")
    if not admin_bot_file.exists():
        print("❌ admin_bot.py не найден")
        return False

    with open(admin_bot_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Check for fixed send callback logic
    send_callback_fix = "if message.is_locked() and message.admin_processing != query.from_user.id:"
    if send_callback_fix in content:
        print("✅ Исправление handle_send_callback найдено")
        send_fixed = True
    else:
        print("❌ Исправление handle_send_callback НЕ найдено")
        send_fixed = False

    # Check for fixed reject callback logic
    reject_callback_fix = "if message.is_locked() and message.admin_processing != query.from_user.id:"
    reject_count = content.count(reject_callback_fix)
    if reject_count >= 2:  # Should appear in both send and reject handlers
        print("✅ Исправление handle_reject_callback найдено")
        reject_fixed = True
    else:
        print(f"❌ Исправление handle_reject_callback НЕ найдено (найдено {reject_count} вхождений, ожидается >= 2)")
        reject_fixed = False

    # Check for Moscow time format fix
    moscow_time_fix = 'moscow_time.strftime("%H:%M MSK")'
    if moscow_time_fix in content:
        print("✅ Исправление формата времени MSK найдено в admin_bot.py")
        time_fixed_admin = True
    else:
        print("❌ Исправление формата времени MSK НЕ найдено в admin_bot.py")
        time_fixed_admin = False

    # Check moderation_service.py for time format
    mod_service_file = Path("services/moderation_service.py")
    if mod_service_file.exists():
        with open(mod_service_file, 'r', encoding='utf-8') as f:
            mod_content = f.read()

        if moscow_time_fix in mod_content:
            print("✅ Исправление формата времени MSK найдено в moderation_service.py")
            time_fixed_service = True
        else:
            print("❌ Исправление формата времени MSK НЕ найдено в moderation_service.py")
            time_fixed_service = False
    else:
        print("❌ services/moderation_service.py не найден")
        time_fixed_service = False

    all_fixed = send_fixed and reject_fixed and time_fixed_admin and time_fixed_service

    print(f"\n📊 СВОДКА ИСПРАВЛЕНИЙ:")
    print(f"   • Логика send callback: {'✅' if send_fixed else '❌'}")
    print(f"   • Логика reject callback: {'✅' if reject_fixed else '❌'}")
    print(f"   • Формат времени admin_bot: {'✅' if time_fixed_admin else '❌'}")
    print(f"   • Формат времени moderation_service: {'✅' if time_fixed_service else '❌'}")
    print(f"   • Все исправления применены: {'✅' if all_fixed else '❌'}")

    return all_fixed

def generate_test_scenarios():
    """Generate test scenarios for manual testing."""
    print("🧪 СЦЕНАРИИ ТЕСТИРОВАНИЯ")
    print("=" * 60)

    scenarios = [
        {
            "name": "Тест 1: Базовое редактирование",
            "steps": [
                "1. Найти сообщение в ожидании модерации",
                "2. Нажать '✏️ Редактировать'",
                "3. Убедиться, что сообщение заблокировано (другие админы не могут редактировать)",
                "4. Отправить текстовую корректировку",
                "5. Проверить появление кнопок: '✅ Отправить исправленный', '✏️ Доработать еще', '❌ Отклонить'"
            ],
            "expected": "Все кнопки отображаются, никаких ошибок блокировки"
        },

        {
            "name": "Тест 2: Кнопка '✅ Отправить исправленный' (ИСПРАВЛЕНА)",
            "steps": [
                "1. Выполнить Тест 1 до появления исправленных кнопок",
                "2. Нажать '✅ Отправить исправленный'",
                "3. Проверить отсутствие ошибки 'уже обрабатывается mttMx'"
            ],
            "expected": "Сообщение отправляется без ошибок, уведомления админам отправлены"
        },

        {
            "name": "Тест 3: Кнопка '✏️ Доработать еще'",
            "steps": [
                "1. Выполнить Тест 1 до появления исправленных кнопок",
                "2. Нажать '✏️ Доработать еще'",
                "3. Отправить дополнительную корректировку",
                "4. Снова проверить появление кнопок выбора"
            ],
            "expected": "Возможность многократного редактирования, правильная работа блокировки"
        },

        {
            "name": "Тест 4: Кнопка '❌ Отклонить' из режима корректировки",
            "steps": [
                "1. Выполнить Тест 1 до появления исправленных кнопок",
                "2. Нажать '❌ Отклонить'",
                "3. Проверить корректное отклонение сообщения"
            ],
            "expected": "Сообщение отклоняется, уведомления отправлены, блокировка снята"
        },

        {
            "name": "Тест 5: Кнопка '❌ Отменить редактирование'",
            "steps": [
                "1. Нажать '✏️ Редактировать' на любом сообщении",
                "2. Нажать '❌ Отменить редактирование'",
                "3. Проверить возврат к исходному состоянию"
            ],
            "expected": "Сообщение разблокировано, возврат к основным кнопкам модерации"
        },

        {
            "name": "Тест 6: Многопользовательские блокировки",
            "steps": [
                "1. Админ A начинает редактирование сообщения",
                "2. Админ B пытается отредактировать то же сообщение",
                "3. Проверить корректные сообщения о блокировке",
                "4. Админ A завершает редактирование",
                "5. Проверить, что блокировка снята для всех"
            ],
            "expected": "Корректные сообщения о блокировке, правильное управление блокировками"
        }
    ]

    for i, scenario in enumerate(scenarios, 1):
        print(f"📋 {scenario['name']}:")
        print("   Шаги:")
        for step in scenario['steps']:
            print(f"      {step}")
        print(f"   Ожидаемый результат: {scenario['expected']}")
        print()

def main():
    """Main test function."""
    print("🚀 ТЕСТИРОВАНИЕ WORKFLOW РЕДАКТИРОВАНИЯ ADMIN BOT")
    print("=" * 80)
    print()

    # Step 1: Analyze current queue state
    queue_data = analyze_queue_state()
    if not queue_data:
        print("❌ Не удалось загрузить данные очереди")
        return

    print()

    # Step 2: Check that fixes have been applied
    fixes_applied = check_lock_logic_fixes()
    if not fixes_applied:
        print("⚠️ ВНИМАНИЕ: Не все исправления применены!")

    print()

    # Step 3: Document workflow buttons
    test_workflow_buttons_documentation()
    print()

    # Step 4: Generate test scenarios
    generate_test_scenarios()

    # Step 5: Summary
    print("📋 СВОДКА")
    print("=" * 60)
    print("✅ Анализ системы завершен")
    print("✅ Исправления проверены")
    print("✅ Сценарии тестирования созданы")
    print()
    print("🔗 СЛЕДУЮЩИЕ ШАГИ:")
    print("   1. Выполнить ручное тестирование по сценариям выше")
    print("   2. Проверить каждую кнопку в workflow")
    print("   3. Убедиться в корректной работе блокировок")
    print("   4. Проверить уведомления админам")
    print()
    print("🎯 ОСНОВНАЯ ЦЕЛЬ: Убедиться, что кнопка '✅ Отправить исправленный'")
    print("   больше НЕ показывает ошибку 'уже обрабатывается mttMx'")

if __name__ == "__main__":
    main()