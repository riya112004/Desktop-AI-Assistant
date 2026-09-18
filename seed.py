"""Load deterministic fake data for local feature development."""

from db.database import Database, ImportantDate, Memory, Reminder, UserProfile


def seed() -> None:
    database = Database()
    database.upsert_profile(UserProfile(name="Alex Morgan", city="Seattle", zodiac_sign="Virgo"))

    family_id = database.add_memory(Memory("family", "Jordan Morgan", {"relationship": "sibling"}))
    database.add_important_date(ImportantDate(family_id, "1990-10-17", "birthday", True))

    vehicle_id = database.add_memory(Memory("vehicle", "Blue Hatchback", {"make": "Example", "model": "Comet", "year": 2022}))
    database.add_important_date(ImportantDate(vehicle_id, "2026-10-02", "service", False))

    policy_id = database.add_memory(Memory("insurance", "Home insurance", {"provider": "Example Mutual", "policy_number": "TEST-001"}))
    database.add_important_date(ImportantDate(policy_id, "2026-10-20", "renewal", True))

    database.add_reminder(Reminder("Review insurance renewal", "2026-10-15T09:00:00+00:00"))
    database.set_state("onboarding_complete", "1")
    database.set_state("last_briefing_date", "2026-09-17")

    print("Seeded profile:", database.get_profile().name)
    print("Upcoming dates:")
    for item in database.dates_due_between("2026-09-17", "2026-10-17"):
        print(f"- {item['title']}: {item['type']} on {item['date']}")


if __name__ == "__main__":
    seed()
