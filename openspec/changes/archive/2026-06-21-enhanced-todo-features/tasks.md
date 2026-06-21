## 1. Todo Model Enhancement

- [x] 1.1 Add `priority` field to Todo class (default: "medium")
- [x] 1.2 Update `from_dict()` method for backward compatibility
- [x] 1.3 Add `is_overdue()` method to Todo class
- [x] 1.4 Add `is_upcoming()` method to Todo class

## 2. Todo Manager Enhancement

- [x] 2.1 Implement `get_today()` method for today's tasks
- [x] 2.2 Implement `get_this_week()` method for weekly tasks
- [x] 2.3 Implement `get_this_month()` method for monthly tasks
- [x] 2.4 Implement `get_upcoming(days=2)` method for upcoming tasks
- [x] 2.5 Implement `get_overdue()` method for overdue tasks
- [x] 2.6 Implement `get_by_priority(priority)` method for priority filtering
- [x] 2.7 Implement `search(keyword)` method for keyword search
- [x] 2.8 Implement `get_statistics()` method for task statistics
- [x] 2.9 Implement `clear_completed()` method for cleaning completed tasks
- [x] 2.10 Implement persistent preference storage for SQLite and JSON backends

## 3. Agent Tools Enhancement

- [x] 3.1 Extend `list_todos` tool to support `time_range` and `priority` parameters
- [x] 3.2 Add `search_todos` tool with keyword parameter
- [x] 3.3 Add `clear_completed` tool
- [x] 3.4 Update tool definitions in TOOL_DEFINITIONS
- [x] 3.5 Add `remember_preference`, `list_preferences`, and `forget_preference` tools
- [x] 3.6 Inject persistent preferences into Agent system prompt

## 4. CLI Enhancement

- [x] 4.1 Implement `/list today` command handler
- [x] 4.2 Implement `/list week` command handler
- [x] 4.3 Implement `/list month` command handler
- [x] 4.4 Implement `/list overdue` command handler
- [x] 4.5 Implement `/list upcoming` command handler
- [x] 4.6 Implement `/list high/medium/low` command handlers
- [x] 4.7 Implement `/search <keyword>` command handler
- [x] 4.8 Implement `/stats` command handler
- [x] 4.9 Implement `/clear` command handler with confirmation
- [x] 4.10 Implement color output for task status and priority
- [x] 4.11 Update `/add` command to support priority prefix
- [x] 4.12 Update `/update` command to support priority field
- [x] 4.13 Implement `/today` personal assistant briefing
- [x] 4.14 Implement `/plan day` daily plan
- [x] 4.15 Implement `/preferences`, `/remember`, and `/forget`
- [x] 4.16 Fix single-argument command parsing for `/add`, `/search`, `/toggle`, and `/delete`

## 5. Testing and Verification

- [x] 5.1 Test time-based filtering commands
- [x] 5.2 Test priority management commands
- [x] 5.3 Test color output display
- [x] 5.4 Test search functionality
- [x] 5.5 Test statistics display
- [x] 5.6 Test clear completed functionality
- [x] 5.7 Test personal assistant briefing and daily plan commands
- [x] 5.8 Test persistent preferences across SQLite and JSON repository instances
- [x] 5.9 Run full unittest suite
