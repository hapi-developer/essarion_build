"""Multi-turn: chain reason() and generate() in a Conversation.

Run with:
    OPENROUTER_API_KEY=... python examples/05_conversation.py
"""

from __future__ import annotations

from essarion_build import Context, Conversation


def main() -> None:
    conv = Conversation(
        context=Context().with_skills(["data_modeling", "database_design", "migrations"])
    )

    print("--- turn 1: schema design ---")
    r1 = conv.reason("design a users-and-orgs schema with row-level multitenancy")
    print(r1.plan)

    print("\n--- turn 2: write the migration ---")
    g2 = conv.generate("write a Postgres SQL migration for the schema above")
    print(g2.code)

    print("\n--- turn 3: tests ---")
    g3 = conv.generate("write a pytest that runs the migration on a temp DB and verifies the constraints")
    print(g3.code)

    print(f"\nTotal usage across {len(conv.history)} turns: {conv.usage.total_tokens} tokens")


if __name__ == "__main__":
    main()
