// Reads Apple Calendar events and Reminders through EventKit and writes them as
// Quarterdeck connector snapshots. Runs on this Mac only; nothing is sent anywhere.
// Usage: QuarterdeckAgenda <connectors-dir> <days>
import Foundation
import EventKit

let args = CommandLine.arguments
guard args.count >= 3, let days = Int(args[2]), (1...60).contains(days) else { exit(2) }
let outDir = URL(fileURLWithPath: args[1], isDirectory: true)
let store = EKEventStore()

func waitFor(_ done: () -> Bool, seconds: Double) {
    let end = Date().addingTimeInterval(seconds)
    while !done() && Date() < end { RunLoop.main.run(until: Date().addingTimeInterval(0.1)) }
}
var evAnswered = false, evOK = false, remAnswered = false, remOK = false
store.requestFullAccessToEvents { g, _ in evOK = g; evAnswered = true }
waitFor({ evAnswered }, seconds: 120)
store.requestFullAccessToReminders { g, _ in remOK = g; remAnswered = true }
waitFor({ remAnswered }, seconds: 120)

let iso = ISO8601DateFormatter()
let human = DateFormatter(); human.dateFormat = "EEE d MMM HH:mm"
let dayOnly = DateFormatter(); dayOnly.dateFormat = "EEE d MMM"
func write(_ name: String, _ items: [[String: Any]], unread: Int) {
    let obj: [String: Any] = ["updated": iso.string(from: Date()), "unread": unread, "items": Array(items.prefix(12))]
    guard let data = try? JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted]) else { return }
    try? data.write(to: outDir.appendingPathComponent(name + ".json"), options: .atomic)
}

let cal = Calendar.current
let dayStart = cal.startOfDay(for: Date())
let end = cal.date(byAdding: .day, value: days, to: dayStart)!

if evOK {
    let pred = store.predicateForEvents(withStart: dayStart, end: end, calendars: nil)
    let events = store.events(matching: pred).filter { $0.endDate > Date() }.sorted { $0.startDate < $1.startDate }
    let items: [[String: Any]] = events.map { e in
        let when = e.isAllDay ? dayOnly.string(from: e.startDate) + ", all day" : human.string(from: e.startDate)
        return ["title": e.title ?? "(no title)", "sub": when + " · " + (e.calendar?.title ?? ""),
                "at": iso.string(from: e.startDate), "new": false]
    }
    let today = events.filter { cal.isDateInToday($0.startDate) }.count
    write("calendar", items, unread: today)
}

if remOK {
    var fetched = false, found: [EKReminder] = []
    store.fetchReminders(matching: store.predicateForReminders(in: nil)) { r in found = r ?? []; fetched = true }
    waitFor({ fetched }, seconds: 30)
    func due(_ r: EKReminder) -> Date? { r.dueDateComponents.flatMap { cal.date(from: $0) } }
    let open = found.filter { !$0.isCompleted && (due($0).map { $0 < end } ?? true) }
    let sorted = open.sorted { (due($0) ?? .distantFuture) < (due($1) ?? .distantFuture) }
    let items: [[String: Any]] = sorted.map { r in
        let d = due(r)
        let sub = (d.map { "due " + human.string(from: $0) } ?? "no date") + " · " + (r.calendar?.title ?? "")
        return ["title": r.title ?? "(no title)", "sub": sub, "at": d.map { iso.string(from: $0) } ?? "", "new": false]
    }
    write("reminders", items, unread: open.filter { (due($0) ?? .distantFuture) < end && cal.isDateInToday(due($0) ?? .distantFuture) || (due($0) ?? .distantFuture) < dayStart }.count)
}

// 0 not asked, 1 restricted, 2 denied, 3 allowed (or full access), 4 write only
let status: [String: Any] = ["at": iso.string(from: Date()), "events": evOK, "reminders": remOK,
    "events_status": EKEventStore.authorizationStatus(for: .event).rawValue,
    "reminders_status": EKEventStore.authorizationStatus(for: .reminder).rawValue]
if let d = try? JSONSerialization.data(withJSONObject: status) {
    try? d.write(to: outDir.deletingLastPathComponent().appendingPathComponent("agenda-status.json"), options: .atomic)
}
