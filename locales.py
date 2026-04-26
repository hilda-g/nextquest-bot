"""
NextQuest Bot — localisation strings
All user-facing messages in EN / RU / EL / UK.
Moderator-only strings (admin panel, approve/reject flow) stay in Russian in bot.py.

Usage:
    from locales import s, LANG_PICKER_KEYBOARD
    await message.reply_text(s(lang, "event_not_found"))
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

STRINGS = {
    # ── Start / onboarding ────────────────────────────────────
    "welcome": {
        "en": "👋 Hi! I'm *NextQuest* — your guide to geek events in Cyprus.\n\nFirst, choose your language:",
        "ru": "👋 Привет! Я *NextQuest* — бот событий гик-сообщества Кипра.\n\nСначала выбери язык:",
        "el": "👋 Γεια! Είμαι το *NextQuest* — ο οδηγός geek εκδηλώσεων στην Κύπρο.\n\nΕπίλεξε γλώσσα:",
        "uk": "👋 Привіт! Я *NextQuest* — бот подій гік-спільноти Кіпру.\n\nСпочатку обери мову:",
    },
    "who_are_you": {
        "en": "Who are you?",
        "ru": "Кто ты?",
        "el": "Ποιος είσαι;",
        "uk": "Хто ти?",
    },
    "btn_participant": {
        "en": "🎲 Participant — looking for events",
        "ru": "🎲 Участник — ищу события",
        "el": "🎲 Συμμετέχων — ψάχνω εκδηλώσεις",
        "uk": "🎲 Учасник — шукаю події",
    },
    "btn_organizer": {
        "en": "🎪 Organizer — adding events",
        "ru": "🎪 Организатор — добавляю события",
        "el": "🎪 Διοργανωτής — προσθέτω εκδηλώσεις",
        "uk": "🎪 Організатор — додаю події",
    },
    "no_org_role": {
        "en": "🎪 To add events you need moderator verification.\n\nSend a request with /request\\_organizer",
        "ru": "🎪 Чтобы добавлять события, нужна верификация модератором.\n\nОтправь запрос командой /request\\_organizer",
        "el": "🎪 Για να προσθέσεις εκδηλώσεις χρειάζεται επαλήθευση.\n\nΑπόστειλε αίτημα με /request\\_organizer",
        "uk": "🎪 Щоб додавати події, потрібна верифікація модератором.\n\nНадішли запит командою /request\\_organizer",
    },
    "need_verification": {
        "en": "⛔ Organizer verification required. Send /request\\_organizer",
        "ru": "⛔ Нужна верификация организатора. Отправь /request\\_organizer",
        "el": "⛔ Απαιτείται επαλήθευση διοργανωτή. Στείλε /request\\_organizer",
        "uk": "⛔ Потрібна верифікація організатора. Надішли /request\\_organizer",
    },

    # ── Main menus ────────────────────────────────────────────
    "menu_organizer": {
        "en": "Organizer menu:",
        "ru": "Меню организатора:",
        "el": "Μενού διοργανωτή:",
        "uk": "Меню організатора:",
    },
    "menu_participant": {
        "en": "Menu:",
        "ru": "Меню:",
        "el": "Μενού:",
        "uk": "Меню:",
    },
    "btn_new_event": {
        "en": "✨ Add event",
        "ru": "✨ Добавить событие",
        "el": "✨ Προσθήκη εκδήλωσης",
        "uk": "✨ Додати подію",
    },
    "btn_my_events": {
        "en": "📋 My events",
        "ru": "📋 Мои события",
        "el": "📋 Οι εκδηλώσεις μου",
        "uk": "📋 Мої події",
    },
    "btn_feedback": {
        "en": "📬 Feedback",
        "ru": "📬 Обратная связь",
        "el": "📬 Σχόλια",
        "uk": "📬 Зворотній зв'язок",
    },
    "btn_my_subs": {
        "en": "🔔 My subscriptions",
        "ru": "🔔 Мои подписки",
        "el": "🔔 Οι συνδρομές μου",
        "uk": "🔔 Мої підписки",
    },
    "btn_upcoming": {
        "en": "🗓 Upcoming events",
        "ru": "🗓 Ближайшие события",
        "el": "🗓 Επερχόμενες εκδηλώσεις",
        "uk": "🗓 Найближчі події",
    },
    "btn_subscribe": {
        "en": "📌 Subscribe to topic",
        "ru": "📌 Подписаться на тему",
        "el": "📌 Εγγραφή σε θέμα",
        "uk": "📌 Підписатись на тему",
    },

    # ── Settings ──────────────────────────────────────────────
    "settings_title": {
        "en": "⚙️ Settings",
        "ru": "⚙️ Настройки",
        "el": "⚙️ Ρυθμίσεις",
        "uk": "⚙️ Налаштування",
    },
    "settings_lang": {
        "en": "🌐 Change language",
        "ru": "🌐 Сменить язык",
        "el": "🌐 Αλλαγή γλώσσας",
        "uk": "🌐 Змінити мову",
    },
    "lang_changed": {
        "en": "✅ Language changed to English 🇬🇧",
        "ru": "✅ Язык изменён на Русский 🇷🇺",
        "el": "✅ Η γλώσσα άλλαξε σε Ελληνικά 🇬🇷",
        "uk": "✅ Мову змінено на Українську 🇺🇦",
    },

    # ── Request organizer ────────────────────────────────────
    "already_organizer": {
        "en": "✅ You're already an organizer!",
        "ru": "✅ Ты уже организатор!",
        "el": "✅ Είσαι ήδη διοργανωτής!",
        "uk": "✅ Ти вже організатор!",
    },
    "org_request_sent": {
        "en": "📬 Request sent to moderator. Please wait for confirmation.",
        "ru": "📬 Запрос отправлен модератору. Ожидай подтверждения.",
        "el": "📬 Αίτημα στάλθηκε στον συντονιστή. Περίμενε επιβεβαίωση.",
        "uk": "📬 Запит надіслано модератору. Очікуй підтвердження.",
    },
    "org_request_approved": {
        "en": "🎉 Your request is approved! You are now a NextQuest organizer.\n\nUse /new\\_event to add an event.",
        "ru": "🎉 Твой запрос одобрен! Теперь ты организатор NextQuest.\n\nИспользуй /new\\_event чтобы добавить событие.",
        "el": "🎉 Το αίτημά σου εγκρίθηκε! Είσαι πλέον διοργανωτής NextQuest.\n\nΧρησιμοποίησε /new\\_event για να προσθέσεις εκδήλωση.",
        "uk": "🎉 Твій запит схвалено! Тепер ти організатор NextQuest.\n\nВикористай /new\\_event щоб додати подію.",
    },
    "org_request_denied": {
        "en": "❌ Your organizer request was declined. Contact the moderator if you have questions.",
        "ru": "❌ Твой запрос на роль организатора отклонён. Напиши модератору если есть вопросы.",
        "el": "❌ Το αίτημά σου για διοργανωτή απορρίφθηκε. Επικοινώνησε με τον συντονιστή αν έχεις ερωτήσεις.",
        "uk": "❌ Твій запит на роль організатора відхилено. Напиши модератору якщо є питання.",
    },

    # ── Generic errors ────────────────────────────────────────
    "event_not_found": {
        "en": "❌ Event not found.",
        "ru": "❌ Событие не найдено.",
        "el": "❌ Η εκδήλωση δεν βρέθηκε.",
        "uk": "❌ Подію не знайдено.",
    },
    "session_expired": {
        "en": "❌ Session expired. Try /new\\_event again.",
        "ru": "❌ Сессия истекла. Попробуй /new\\_event снова.",
        "el": "❌ Η συνεδρία έληξε. Δοκίμασε /new\\_event ξανά.",
        "uk": "❌ Сесія закінчилась. Спробуй /new\\_event знову.",
    },
    "session_expired_restart": {
        "en": "❌ Session expired. Start over: /new\\_event",
        "ru": "❌ Сессия истекла. Начни заново: /new\\_event",
        "el": "❌ Η συνεδρία έληξε. Ξεκίνα από την αρχή: /new\\_event",
        "uk": "❌ Сесія закінчилась. Почни знову: /new\\_event",
    },
    "cancelled": {
        "en": "Cancelled.",
        "ru": "Отменено.",
        "el": "Ακυρώθηκε.",
        "uk": "Скасовано.",
    },
    "save_error": {
        "en": "❌ Save error. Please try again.",
        "ru": "❌ Ошибка сохранения. Попробуй ещё раз.",
        "el": "❌ Σφάλμα αποθήκευσης. Δοκίμασε ξανά.",
        "uk": "❌ Помилка збереження. Спробуй ще раз.",
    },
    "expect_text_or_photo": {
        "en": "❌ Please send text or a photo.",
        "ru": "❌ Ожидается текст или фото.",
        "el": "❌ Παρακαλώ στείλε κείμενο ή φωτογραφία.",
        "uk": "❌ Надішли текст або фото.",
    },
    "invalid_date_format": {
        "en": "❌ Wrong format. Use: YYYY-MM-DD HH:MM",
        "ru": "❌ Неверный формат. Используй: YYYY-MM-DD HH:MM",
        "el": "❌ Λάθος μορφή. Χρησιμοποίησε: YYYY-MM-DD HH:MM",
        "uk": "❌ Невірний формат. Використовуй: YYYY-MM-DD HH:MM",
    },
    "invalid_number": {
        "en": "❌ Enter a number or `-`.",
        "ru": "❌ Введи число или `-`.",
        "el": "❌ Εισαγωγή αριθμού ή `-`.",
        "uk": "❌ Введи число або `-`.",
    },
    "need_image_or_url": {
        "en": "❌ Please send an image or a link (https://...)",
        "ru": "❌ Нужна картинка или ссылка (https://...)",
        "el": "❌ Στείλε εικόνα ή σύνδεσμο (https://...)",
        "uk": "❌ Потрібна картинка або посилання (https://...)",
    },

    # ── Wizard: new event ────────────────────────────────────
    "draft_found": {
        "en": "You have an unfinished draft: *{title}*\nContinue or start fresh?",
        "ru": "У тебя есть незавершённый черновик: *{title}*\nПродолжить или начать заново?",
        "el": "Έχεις ένα ημιτελές προσχέδιο: *{title}*\nΣυνέχεια ή νέα αρχή;",
        "uk": "У тебе є незавершений чернетка: *{title}*\nПродовжити чи почати знову?",
    },
    "btn_continue_draft": {
        "en": "▶️ Continue",
        "ru": "▶️ Продолжить",
        "el": "▶️ Συνέχεια",
        "uk": "▶️ Продовжити",
    },
    "btn_new_draft": {
        "en": "🗑 Start fresh",
        "ru": "🗑 Начать заново",
        "el": "🗑 Νέα αρχή",
        "uk": "🗑 Почати знову",
    },
    "step_category": {
        "en": "Step 1/5: *Event category?*",
        "ru": "Шаг 1/5: *Категория события?*",
        "el": "Βήμα 1/5: *Κατηγορία εκδήλωσης;*",
        "uk": "Крок 1/5: *Категорія події?*",
    },
    "step_date_start": {
        "en": "Step 2/5: *Start date — year?*",
        "ru": "Шаг 2/5: *Дата начала — год?*",
        "el": "Βήμα 2/5: *Ημερομηνία έναρξης — έτος;*",
        "uk": "Крок 2/5: *Дата початку — рік?*",
    },
    "ask_month": {
        "en": "Month?",
        "ru": "Месяц?",
        "el": "Μήνας;",
        "uk": "Місяць?",
    },
    "ask_day": {
        "en": "Day?",
        "ru": "День?",
        "el": "Ημέρα;",
        "uk": "День?",
    },
    "ask_hour_start": {
        "en": "Start hour?",
        "ru": "Час начала?",
        "el": "Ώρα έναρξης;",
        "uk": "Година початку?",
    },
    "ask_minute": {
        "en": "Minutes?",
        "ru": "Минуты?",
        "el": "Λεπτά;",
        "uk": "Хвилини?",
    },
    "ask_end_year": {
        "en": "End year?",
        "ru": "Год окончания?",
        "el": "Έτος λήξης;",
        "uk": "Рік закінчення?",
    },
    "ask_end_month": {
        "en": "End month?",
        "ru": "Месяц окончания?",
        "el": "Μήνας λήξης;",
        "uk": "Місяць закінчення?",
    },
    "ask_end_day": {
        "en": "End day?",
        "ru": "День окончания?",
        "el": "Ημέρα λήξης;",
        "uk": "День закінчення?",
    },
    "ask_end_hour": {
        "en": "End hour?",
        "ru": "Час окончания?",
        "el": "Ώρα λήξης;",
        "uk": "Година закінчення?",
    },
    "ask_end_minute": {
        "en": "End minutes?",
        "ru": "Минуты окончания?",
        "el": "Λεπτά λήξης;",
        "uk": "Хвилини закінчення?",
    },
    "step_city": {
        "en": "Step 3/5: *City?*",
        "ru": "Шаг 3/5: *Город?*",
        "el": "Βήμα 3/5: *Πόλη;*",
        "uk": "Крок 3/5: *Місто?*",
    },
    "ask_address": {
        "en": "Address? (street, venue)",
        "ru": "Адрес? (улица, заведение)",
        "el": "Διεύθυνση; (οδός, χώρος)",
        "uk": "Адреса? (вулиця, заклад)",
    },
    "ask_limit": {
        "en": "Participant limit?",
        "ru": "Лимит участников?",
        "el": "Όριο συμμετεχόντων;",
        "uk": "Ліміт учасників?",
    },
    "btn_no_limit": {
        "en": "No limit",
        "ru": "Без лимита",
        "el": "Χωρίς όριο",
        "uk": "Без ліміту",
    },
    "ask_format": {
        "en": "Event format?",
        "ru": "Формат события?",
        "el": "Μορφή εκδήλωσης;",
        "uk": "Формат події?",
    },
    "btn_format_official": {
        "en": "🎉 Official — public event",
        "ru": "🎉 Official — публичное мероприятие",
        "el": "🎉 Official — δημόσια εκδήλωση",
        "uk": "🎉 Official — публічний захід",
    },
    "btn_format_private": {
        "en": "🔒 Private — closed party",
        "ru": "🔒 Private — закрытая вечеринка",
        "el": "🔒 Private — κλειστή εκδήλωση",
        "uk": "🔒 Private — закрита вечірка",
    },
    "step_title": {
        "en": "Step 4/5: *Event name?*",
        "ru": "Шаг 4/5: *Название события?*",
        "el": "Βήμα 4/5: *Όνομα εκδήλωσης;*",
        "uk": "Крок 4/5: *Назва події?*",
    },
    "ask_description": {
        "en": "Event description:",
        "ru": "Описание события:",
        "el": "Περιγραφή εκδήλωσης:",
        "uk": "Опис події:",
    },
    "ask_photo": {
        "en": "Cover photo — send an image or a link (https://...):",
        "ru": "Фото обложки — отправь картинку или ссылку (https://...):",
        "el": "Εξώφυλλο — στείλε εικόνα ή σύνδεσμο (https://...):",
        "uk": "Фото обкладинки — надішли картинку або посилання (https://...):",
    },
    "ask_has_reg_url": {
        "en": "Do you have a registration link?",
        "ru": "Есть ссылка на регистрацию?",
        "el": "Έχεις σύνδεσμο εγγραφής;",
        "uk": "Є посилання на реєстрацію?",
    },
    "btn_yes": {
        "en": "✅ Yes",
        "ru": "✅ Да",
        "el": "✅ Ναι",
        "uk": "✅ Так",
    },
    "btn_no": {
        "en": "❌ No",
        "ru": "❌ Нет",
        "el": "❌ Όχι",
        "uk": "❌ Ні",
    },
    "ask_reg_url": {
        "en": "Send the registration link:",
        "ru": "Отправь ссылку на регистрацию:",
        "el": "Στείλε τον σύνδεσμο εγγραφής:",
        "uk": "Надішли посилання на реєстрацію:",
    },
    "ask_organizer_contacts": {
        "en": "How can participants reach you to register?\nSend @username, link, phone or any text:",
        "ru": "Как с тобой связаться для регистрации?\nНапиши @username, ссылку, телефон или любой текст:",
        "el": "Πώς μπορούν να επικοινωνήσουν μαζί σου;\nΣτείλε @username, σύνδεσμο, τηλέφωνο ή οποιοδήποτε κείμενο:",
        "uk": "Як з тобою зв'язатись для реєстрації?\nНапиши @username, посилання, телефон або будь-який текст:",
    },
    "event_cancelled_creation": {
        "en": "❌ Event creation cancelled.",
        "ru": "❌ Создание события отменено.",
        "el": "❌ Η δημιουργία εκδήλωσης ακυρώθηκε.",
        "uk": "❌ Створення події скасовано.",
    },
    "event_submitted": {
        "en": "✅ Event submitted for moderation!",
        "ru": "✅ Событие отправлено на модерацию!",
        "el": "✅ Η εκδήλωση υποβλήθηκε για έλεγχο!",
        "uk": "✅ Подію надіслано на модерацію!",
    },

    # ── Inline edit (fix before submit) ──────────────────────
    "edit_what": {
        "en": "✏️ What do you want to fix?",
        "ru": "✏️ Что хочешь исправить?",
        "el": "✏️ Τι θέλεις να διορθώσεις;",
        "uk": "✏️ Що хочеш виправити?",
    },
    "edit_back_to_preview": {
        "en": "✅ All good — back to preview",
        "ru": "✅ Всё верно — вернуться к превью",
        "el": "✅ Όλα καλά — επιστροφή στην προεπισκόπηση",
        "uk": "✅ Все вірно — повернутись до перегляду",
    },
    "ask_select_category": {
        "en": "Choose category:",
        "ru": "Выбери категорию:",
        "el": "Επίλεξε κατηγορία:",
        "uk": "Обери категорію:",
    },
    "ask_select_city": {
        "en": "Choose city:",
        "ru": "Выбери город:",
        "el": "Επίλεξε πόλη:",
        "uk": "Обери місто:",
    },
    "ask_new_limit": {
        "en": "New participant limit:",
        "ru": "Новый лимит участников:",
        "el": "Νέο όριο συμμετεχόντων:",
        "uk": "Новий ліміт учасників:",
    },
    "prompts_title":              {"en": "New name:",               "ru": "Новое название:",              "el": "Νέο όνομα:",                  "uk": "Нова назва:"},
    "prompts_description":        {"en": "New description:",        "ru": "Новое описание:",              "el": "Νέα περιγραφή:",              "uk": "Новий опис:"},
    "prompts_location_address":   {"en": "New address:",            "ru": "Новый адрес:",                 "el": "Νέα διεύθυνση:",              "uk": "Нова адреса:"},
    "prompts_date_start":         {"en": "New start date (YYYY-MM-DD HH:MM):", "ru": "Новая дата начала (YYYY-MM-DD HH:MM):", "el": "Νέα ημερομηνία έναρξης (YYYY-MM-DD HH:MM):", "uk": "Нова дата початку (YYYY-MM-DD HH:MM):"},
    "prompts_date_end":           {"en": "New end date (YYYY-MM-DD HH:MM) or `-` to remove:", "ru": "Новая дата конца (YYYY-MM-DD HH:MM) или `-` чтобы убрать:", "el": "Νέα ημερομηνία λήξης ή `-` για αφαίρεση:", "uk": "Нова дата кінця (YYYY-MM-DD HH:MM) або `-` щоб прибрати:"},
    "prompts_external_url":       {"en": "New registration link (or `-` to remove):", "ru": "Новая ссылка на регистрацию (или `-` чтобы убрать):", "el": "Νέος σύνδεσμος εγγραφής (ή `-` για αφαίρεση):", "uk": "Нове посилання на реєстрацію (або `-` щоб прибрати):"},
    "prompts_organizer_contacts": {"en": "Organizer contact (@username, link, phone) or `-` to remove:", "ru": "Контакт организатора (@username, ссылка, телефон) или `-` чтобы убрать:", "el": "Επαφή διοργανωτή ή `-` για αφαίρεση:", "uk": "Контакт організатора або `-` щоб прибрати:"},
    "prompts_cover_image_url":    {"en": "New cover — link (https://...) or send a photo:", "ru": "Новая обложка — ссылка (https://...) или отправь фото:", "el": "Νέο εξώφυλλο — σύνδεσμος ή φωτογραφία:", "uk": "Нова обкладинка — посилання або фото:"},

    # ── My events ────────────────────────────────────────────
    "no_events_yet": {
        "en": "You have no events yet. Use /new\\_event to add one!",
        "ru": "У тебя пока нет событий. /new\\_event чтобы добавить!",
        "el": "Δεν έχεις εκδηλώσεις ακόμα. Χρησιμοποίησε /new\\_event!",
        "uk": "У тебе поки немає подій. /new\\_event щоб додати!",
    },
    "not_your_event": {
        "en": "⛔ This is not your event.",
        "ru": "⛔ Это не твоё событие.",
        "el": "⛔ Αυτή δεν είναι η εκδήλωσή σου.",
        "uk": "⛔ Це не твоя подія.",
    },
    "btn_cancel_event": {
        "en": "🚫 Cancel",
        "ru": "🚫 Отменить",
        "el": "🚫 Ακύρωση",
        "uk": "🚫 Скасувати",
    },
    "btn_share": {
        "en": "🔗 Share",
        "ru": "🔗 Поделиться",
        "el": "🔗 Κοινοποίηση",
        "uk": "🔗 Поділитись",
    },
    "ask_cancel_reason": {
        "en": "Cancelling *{title}*.\nState a reason? (or send `-`)",
        "ru": "Отменяем *{title}*.\nУказать причину? (или отправь `-`)",
        "el": "Ακύρωση *{title}*.\nΑναφέρεις λόγο; (ή στείλε `-`)",
        "uk": "Скасовуємо *{title}*.\nВказати причину? (або надішли `-`)",
    },
    "event_cancelled": {
        "en": "🚫 Event cancelled.",
        "ru": "🚫 Событие отменено.",
        "el": "🚫 Η εκδήλωση ακυρώθηκε.",
        "uk": "🚫 Подію скасовано.",
    },
    "event_cancelled_notify": {
        "en": "❌ Event *{title}* has been cancelled.{reason}",
        "ru": "❌ Событие *{title}* отменено.{reason}",
        "el": "❌ Η εκδήλωση *{title}* ακυρώθηκε.{reason}",
        "uk": "❌ Подію *{title}* скасовано.{reason}",
    },
    "cancel_reason_prefix": {
        "en": "\n\nReason: {reason}",
        "ru": "\n\nПричина: {reason}",
        "el": "\n\nΛόγος: {reason}",
        "uk": "\n\nПричина: {reason}",
    },
    "share_announce": {
        "en": "Ready-made announcement for reposting:\n\n{text}\n\n_Copy and send to your Telegram chat_",
        "ru": "Готовый анонс для репоста:\n\n{text}\n\n_Скопируй и отправь в свой Telegram-чат_",
        "el": "Έτοιμη ανακοίνωση για αναδημοσίευση:\n\n{text}\n\n_Αντίγραψε και στείλε στο Telegram chat σου_",
        "uk": "Готовий анонс для репосту:\n\n{text}\n\n_Скопіюй та надішли у свій Telegram-чат_",
    },

    # ── Upcoming events ──────────────────────────────────────
    "no_upcoming": {
        "en": "No upcoming events right now.",
        "ru": "Ближайших событий пока нет.",
        "el": "Δεν υπάρχουν επερχόμενες εκδηλώσεις αυτή τη στιγμή.",
        "uk": "Найближчих подій поки немає.",
    },
    "btn_notify_me": {
        "en": "🔔 Notify me",
        "ru": "🔔 Напомни мне",
        "el": "🔔 Ειδοποίησέ με",
        "uk": "🔔 Нагадай мені",
    },
    "btn_register": {
        "en": "🔗 Register",
        "ru": "🔗 Регистрация",
        "el": "🔗 Εγγραφή",
        "uk": "🔗 Реєстрація",
    },
    "already_subscribed": {
        "en": "Already subscribed!",
        "ru": "Уже подписан!",
        "el": "Ήδη εγγεγραμμένος!",
        "uk": "Вже підписаний!",
    },
    "reminder_set": {
        "en": "🔔 Reminder set!",
        "ru": "🔔 Напоминание установлено!",
        "el": "🔔 Υπενθύμιση ορίστηκε!",
        "uk": "🔔 Нагадування встановлено!",
    },
    "btn_unsubscribe": {
        "en": "❌ Unsubscribe",
        "ru": "❌ Отписаться",
        "el": "❌ Κατάργηση εγγραφής",
        "uk": "❌ Відписатись",
    },
    "upsell_cat": {
        "en": "Want to receive all new {cat} events?",
        "ru": "Хочешь получать все новые события {cat}?",
        "el": "Θέλεις να λαμβάνεις όλες τις νέες εκδηλώσεις {cat};",
        "uk": "Хочеш отримувати всі нові події {cat}?",
    },
    "btn_sub_cat": {
        "en": "✅ Subscribe to {cat}",
        "ru": "✅ Подписаться на {cat}",
        "el": "✅ Εγγραφή σε {cat}",
        "uk": "✅ Підписатись на {cat}",
    },
    "btn_no_thanks": {
        "en": "No, thanks",
        "ru": "Нет, спасибо",
        "el": "Όχι, ευχαριστώ",
        "uk": "Ні, дякую",
    },

    # ── My subscriptions ─────────────────────────────────────
    "no_subscriptions": {
        "en": "No subscriptions.\n/events — events\n/subscribe — subscribe to categories",
        "ru": "Подписок нет.\n/events — события\n/subscribe — подписаться на категории",
        "el": "Δεν υπάρχουν συνδρομές.\n/events — εκδηλώσεις\n/subscribe — εγγραφή σε κατηγορίες",
        "uk": "Підписок немає.\n/events — події\n/subscribe — підписатись на категорії",
    },
    "subs_on_events": {
        "en": "*On events:*",
        "ru": "*На события:*",
        "el": "*Σε εκδηλώσεις:*",
        "uk": "*На події:*",
    },
    "subs_on_cats": {
        "en": "\n*On categories:*",
        "ru": "\n*На категории:*",
        "el": "\n*Σε κατηγορίες:*",
        "uk": "\n*На категорії:*",
    },
    "btn_unsub_prefix": {
        "en": "Unsubscribe: ",
        "ru": "Отписаться: ",
        "el": "Κατάργηση: ",
        "uk": "Відписатись: ",
    },
    "btn_add_cat": {
        "en": "+ Add category",
        "ru": "+ Добавить категорию",
        "el": "+ Προσθήκη κατηγορίας",
        "uk": "+ Додати категорію",
    },
    "unsubscribed": {
        "en": "✅ Unsubscribed.",
        "ru": "✅ Отписка оформлена.",
        "el": "✅ Η εγγραφή ακυρώθηκε.",
        "uk": "✅ Відписано.",
    },
    "select_categories": {
        "en": "Choose categories (tap to toggle):",
        "ru": "Выбери категории (нажми чтобы переключить):",
        "el": "Επίλεξε κατηγορίες (πάτησε για εναλλαγή):",
        "uk": "Обери категорії (натисни щоб переключити):",
    },
    "btn_done": {
        "en": "Done ✔",
        "ru": "Готово ✔",
        "el": "Έτοιμο ✔",
        "uk": "Готово ✔",
    },
    "settings_saved": {
        "en": "✅ Settings saved!",
        "ru": "✅ Настройки сохранены!",
        "el": "✅ Οι ρυθμίσεις αποθηκεύτηκαν!",
        "uk": "✅ Налаштування збережено!",
    },
    "cant_come": {
        "en": "Got it, unsubscribed. See you at another event! 👋",
        "ru": "Понял, отписал тебя. Увидимся на другом событии! 👋",
        "el": "Εντάξει, σε απεγγράψαμε. Τα λέμε σε άλλη εκδήλωση! 👋",
        "uk": "Зрозуміло, відписав тебе. Побачимось на іншій події! 👋",
    },

    # ── Feedback ─────────────────────────────────────────────
    "feedback_title": {
        "en": "📬 Feedback",
        "ru": "📬 Обратная связь",
        "el": "📬 Σχόλια",
        "uk": "📬 Зворотній зв'язок",
    },
    "btn_event_status": {
        "en": "📊 Event status",
        "ru": "📊 Статус события",
        "el": "📊 Κατάσταση εκδήλωσης",
        "uk": "📊 Статус події",
    },
    "btn_contact_mod": {
        "en": "✉️ Message moderator",
        "ru": "✉️ Написать модератору",
        "el": "✉️ Μήνυμα στον συντονιστή",
        "uk": "✉️ Написати модератору",
    },
    "no_events_for_status": {
        "en": "You have no events.",
        "ru": "У тебя нет событий.",
        "el": "Δεν έχεις εκδηλώσεις.",
        "uk": "У тебе немає подій.",
    },
    "select_event": {
        "en": "Choose event:",
        "ru": "Выбери событие:",
        "el": "Επίλεξε εκδήλωση:",
        "uk": "Обери подію:",
    },
    "ask_mod_message": {
        "en": "Write a message to the moderator:",
        "ru": "Напиши сообщение модератору:",
        "el": "Γράψε μήνυμα στον συντονιστή:",
        "uk": "Напиши повідомлення модератору:",
    },
    "mod_message_sent": {
        "en": "✅ Message sent to moderator.",
        "ru": "✅ Сообщение отправлено модератору.",
        "el": "✅ Το μήνυμα στάλθηκε στον συντονιστή.",
        "uk": "✅ Повідомлення надіслано модератору.",
    },

    # ── Reminders (sent to participant) ──────────────────────
    "reminder_text": {
        "en": "⏰ *Reminder!* The event *{title}* starts soon.\n\n📅 {date}\n📍 {city} · {address}",
        "ru": "⏰ *Напоминание!* Событие *{title}* скоро начнётся.\n\n📅 {date}\n📍 {city} · {address}",
        "el": "⏰ *Υπενθύμιση!* Η εκδήλωση *{title}* ξεκινά σύντομα.\n\n📅 {date}\n📍 {city} · {address}",
        "uk": "⏰ *Нагадування!* Подія *{title}* незабаром починається.\n\n📅 {date}\n📍 {city} · {address}",
    },

    # ── Draft reminder (sent to organizer) ───────────────────
    "draft_reminder": {
        "en": "📝 You have an unfinished event draft!\n\nCategory: {cat}\nTitle: {title}\n\nContinue or delete it via /new\\_event",
        "ru": "📝 У тебя есть незавершённый черновик события!\n\nКатегория: {cat}\nНазвание: {title}\n\nПродолжи или удали его через /new\\_event",
        "el": "📝 Έχεις ένα ημιτελές προσχέδιο εκδήλωσης!\n\nΚατηγορία: {cat}\nΤίτλος: {title}\n\nΣυνέχισε ή διέγραψέ το μέσω /new\\_event",
        "uk": "📝 У тебе є незавершена чернетка події!\n\nКатегорія: {cat}\nНазва: {title}\n\nПродовж або видали через /new\\_event",
    },

    # ── End registration ─────────────────────────────────────
    "reg_reminder_7d": {
        "en": "⏰ *Event in 7 days!*\n\n📌 *{title}*\n📅 {date}\n👥 Limit: {limit} spots\n\nIf all spots are taken — tap *End Registration* to mark it as *Full* on the site.",
        "ru": "⏰ *Событие через 7 дней!*\n\n📌 *{title}*\n📅 {date}\n👥 Лимит: {limit} мест\n\nЕсли все места уже заняты — нажми *End Registration*, чтобы обновить статус до *Full* на сайте.",
        "el": "⏰ *Εκδήλωση σε 7 ημέρες!*\n\n📌 *{title}*\n📅 {date}\n👥 Όριο: {limit} θέσεις\n\nΑν όλες οι θέσεις είναι κατειλημμένες — πάτησε *End Registration*.",
        "uk": "⏰ *Подія через 7 днів!*\n\n📌 *{title}*\n📅 {date}\n👥 Ліміт: {limit} місць\n\nЯкщо всі місця вже зайняті — натисни *End Registration*, щоб оновити статус до *Full* на сайті.",
    },
    "close_reg_confirm": {
        "en": "🔒 *Close registration?*\n\n📌 *{title}*\n👥 Limit: {limit} spots\n\nThis will mark it as *Full* on the site and notify all subscribers.",
        "ru": "🔒 *Закрыть регистрацию?*\n\n📌 *{title}*\n👥 Лимит: {limit} мест\n\nЭто обновит статус до *Full* на сайте и уведомит всех подписчиков.",
        "el": "🔒 *Κλείσιμο εγγραφών;*\n\n📌 *{title}*\n👥 Όριο: {limit} θέσεις\n\nΘα σημανθεί ως *Full* και θα ειδοποιηθούν οι συνδρομητές.",
        "uk": "🔒 *Закрити реєстрацію?*\n\n📌 *{title}*\n👥 Ліміт: {limit} місць\n\nЦе оновить статус до *Full* на сайті та сповістить підписників.",
    },
    "btn_close_reg": {
        "en": "✅ Yes, close registration",
        "ru": "✅ Да, закрыть регистрацию",
        "el": "✅ Ναι, κλείσιμο εγγραφών",
        "uk": "✅ Так, закрити реєстрацію",
    },
    "btn_cancel": {
        "en": "❌ Cancel",
        "ru": "❌ Отмена",
        "el": "❌ Ακύρωση",
        "uk": "❌ Скасувати",
    },
    "reg_closed_done": {
        "en": "✅ Done! *{title}* is now marked as *Full* on the site.",
        "ru": "✅ Готово! *{title}* теперь отмечено как *Full* на сайте.",
        "el": "✅ Έτοιμο! *{title}* σημάνθηκε ως *Full* στον ιστότοπο.",
        "uk": "✅ Готово! *{title}* тепер позначено як *Full* на сайті.",
    },
    "reg_closed_notify": {
        "en": "🔒 *Registration closed!*\n\n📌 *{title}*\n📅 {date}\n👥 All spots taken.\n\nSee you at the event! 🎉",
        "ru": "🔒 *Регистрация закрыта!*\n\n📌 *{title}*\n📅 {date}\n👥 Все места заняты.\n\nУвидимся на событии! 🎉",
        "el": "🔒 *Εγγραφές έκλεισαν!*\n\n📌 *{title}*\n📅 {date}\n👥 Όλες οι θέσεις κατειλημμένες.\n\nΤα λέμε στην εκδήλωση! 🎉",
        "uk": "🔒 *Реєстрацію закрито!*\n\n📌 *{title}*\n📅 {date}\n👥 Всі місця зайняті.\n\nПобачимось на події! 🎉",
    },
    "reg_still_open": {
        "en": "Got it, registration stays open.",
        "ru": "Понял, регистрация пока открыта.",
        "el": "Εντάξει, οι εγγραφές παραμένουν ανοιχτές.",
        "uk": "Зрозуміло, реєстрація залишається відкритою.",
    },
    "reg_cancel": {
        "en": "Cancelled. Registration remains open.",
        "ru": "Отменено. Регистрация по-прежнему открыта.",
        "el": "Ακυρώθηκε. Οι εγγραφές παραμένουν ανοιχτές.",
        "uk": "Скасовано. Реєстрація залишається відкритою.",
    },

    # ── Event card (shown to participant) ────────────────────
    "card_no_limit": {
        "en": "no limit",
        "ru": "без лимита",
        "el": "χωρίς όριο",
        "uk": "без ліміту",
    },
    "card_subscribe_reminder": {
        "en": "🔔 Subscribe for reminder",
        "ru": "🔔 Подписаться на напоминание",
        "el": "🔔 Εγγραφή για υπενθύμιση",
        "uk": "🔔 Підписатись на нагадування",
    },
    "card_event_page": {
        "en": "🌐 Event page",
        "ru": "🌐 Страница события",
        "el": "🌐 Σελίδα εκδήλωσης",
        "uk": "🌐 Сторінка події",
    },
    "card_add_to_calendar": {
        "en": "📅 Add to Google Calendar",
        "ru": "📅 Добавить в Google Календарь",
        "el": "📅 Προσθήκη στο Google Calendar",
        "uk": "📅 Додати до Google Календаря",
    },
    "card_add_your_event": {
        "en": "⭐ Want to add your own event? Message the bot!",
        "ru": "⭐ Хочешь добавить своё событие? Напиши боту!",
        "el": "⭐ Θέλεις να προσθέσεις τη δική σου εκδήλωση; Γράψε στο bot!",
        "uk": "⭐ Хочеш додати свою подію? Напиши боту!",
    },
    "card_organizer_reg": {
        "en": "⭐ Organizer: [Register]({url})",
        "ru": "⭐ Организатор: [Регистрация]({url})",
        "el": "⭐ Διοργανωτής: [Εγγραφή]({url})",
        "uk": "⭐ Організатор: [Реєстрація]({url})",
    },
    "card_organizer_contact": {
        "en": "📋 Organizer contact: {contact}",
        "ru": "📋 Контакт организатора: {contact}",
        "el": "📋 Επαφή διοργανωτή: {contact}",
        "uk": "📋 Контакт організатора: {contact}",
    },

    # ── Wizard: cancelled / draft ─────────────────────────────
    "wizard_cancelled": {
        "en": "Cancelled. Draft saved — continue via /new\\_event",
        "ru": "Отменено. Черновик сохранён — продолжи через /new\\_event",
        "el": "Ακυρώθηκε. Το προσχέδιο αποθηκεύτηκε — συνέχισε μέσω /new\\_event",
        "uk": "Скасовано. Чернетку збережено — продовж через /new\\_event",
    },
    "edit_cancelled": {
        "en": "Edit cancelled.",
        "ru": "Редактирование отменено.",
        "el": "Η επεξεργασία ακυρώθηκε.",
        "uk": "Редагування скасовано.",
    },
    "card_spots": {
        "en": "spots", "ru": "мест", "el": "θέσεις", "uk": "місць",
    },
    "step_preview": {
        "en": "Step 5/5: *Preview* (updated)",
        "ru": "Шаг 5/5: *Превью* (обновлено)",
        "el": "Βήμα 5/5: *Προεπισκόπηση* (ενημερώθηκε)",
        "uk": "Крок 5/5: *Перегляд* (оновлено)",
    },
    "preview_ok": {
        "en": "Everything correct?",
        "ru": "Всё верно?",
        "el": "Όλα σωστά;",
        "uk": "Все вірно?",
    },
    "btn_submit": {
        "en": "📤 Submit for moderation",
        "ru": "📤 Отправить на модерацию",
        "el": "📤 Υποβολή για έλεγχο",
        "uk": "📤 Надіслати на модерацію",
    },
    "btn_edit_more": {
        "en": "✏️ Edit more",
        "ru": "✏️ Исправить ещё",
        "el": "✏️ Περισσότερες διορθώσεις",
        "uk": "✏️ Виправити ще",
    },
    "btn_cancel_str": {
        "en": "🗑 Cancel",
        "ru": "🗑 Отмена",
        "el": "🗑 Ακύρωση",
        "uk": "🗑 Скасувати",
    },
    "start_confirmed": {
        "en": "Start: *{dt}* ✓\n\nMulti-day event?",
        "ru": "Начало: *{dt}* ✓\n\nМногодневное событие?",
        "el": "Έναρξη: *{dt}* ✓\n\nΠολυήμερη εκδήλωση;",
        "uk": "Початок: *{dt}* ✓\n\nБагатоденна подія?",
    },
    "subcat_unsub": {
        "en": "Unsubscribed from {cat}",
        "ru": "Отписка от {cat}",
        "el": "Κατάργηση εγγραφής από {cat}",
        "uk": "Відписка від {cat}",
    },
    "subcat_sub": {
        "en": "Subscribed to {cat}",
        "ru": "Подписка на {cat}",
        "el": "Εγγραφή σε {cat}",
        "uk": "Підписка на {cat}",
    },
    "event_status_info": {
        "en": "{icon} *{title}*\nStatus: {status}\n👥 Subscribers: {count}\n{reject}",
        "ru": "{icon} *{title}*\nСтатус: {status}\n👥 Подписчиков: {count}\n{reject}",
        "el": "{icon} *{title}*\nΚατάσταση: {status}\n👥 Συνδρομητές: {count}\n{reject}",
        "uk": "{icon} *{title}*\nСтатус: {status}\n👥 Підписників: {count}\n{reject}",
    },
}
def s(lang: str, key: str, **kwargs) -> str:
    """
    Return localised string for given lang and key.
    Falls back to Russian if lang not found, then to the key itself.
    Supports .format() kwargs, e.g. s(lang, "draft_found", title="My Event")
    """
    lang = lang if lang in ("en", "ru", "el", "uk") else "ru"
    entry = STRINGS.get(key, {})
    text = entry.get(lang) or entry.get("ru") or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text


LANG_PICKER_KEYBOARD = InlineKeyboardMarkup([[
    InlineKeyboardButton("🇬🇧 EN", callback_data="setlang:en"),
    InlineKeyboardButton("🇷🇺 RU", callback_data="setlang:ru"),
    InlineKeyboardButton("🇬🇷 GR", callback_data="setlang:el"),
    InlineKeyboardButton("🇺🇦 UK", callback_data="setlang:uk"),
]])
