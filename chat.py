"""Terminal chat with the database agent.

    python chat.py                  start a new conversation
    python chat.py --list           show your conversations
    python chat.py --last           continue your most recent conversation
    python chat.py --continue 12    continue conversation 12

Type a question and press Enter. Type "exit" to quit.
"""
import argparse
import sys

from app.agent import NLDBAgent
from app.context.conversation_store import ConversationStore
from app.database.connection import check_connection

MAX_TABLE_ROWS = 20   # print at most this many rows per answer
MAX_CELL_WIDTH = 40   # cut very long values so the table stays readable
RECAP_MESSAGES = 6    # how many earlier messages to show when continuing


def print_table(columns, rows):
    """Print rows as a simple text table with aligned columns."""
    if not columns:
        return
    shown = [
        [("" if value is None else str(value))[:MAX_CELL_WIDTH] for value in row]
        for row in rows[:MAX_TABLE_ROWS]
    ]
    widths = [
        max([len(column)] + [len(row[i]) for row in shown])
        for i, column in enumerate(columns)
    ]
    print(("  " + " | ".join(column.ljust(w) for column, w in zip(columns, widths))).rstrip())
    print("  " + "-+-".join("-" * w for w in widths))
    for row in shown:
        print(("  " + " | ".join(value.ljust(w) for value, w in zip(row, widths))).rstrip())
    if len(rows) > MAX_TABLE_ROWS:
        print("  ... {} more rows not shown".format(len(rows) - MAX_TABLE_ROWS))


def print_conversations(conversations):
    if not conversations:
        print("No conversations yet. Start one with: python chat.py")
        return
    print_table(
        ["id", "title", "last active"],
        [
            [c["id"], c["title"] or "(untitled)", c["last_active_at"].astimezone().strftime("%Y-%m-%d %H:%M")]
            for c in conversations
        ],
    )


def print_recap(store, conversation_id):
    """Show the last few messages, so the user remembers where they stopped."""
    for message in store.get_history(conversation_id, limit=RECAP_MESSAGES):
        speaker = "You" if message["role"] == "user" else "Agent"
        print("{}: {}".format(speaker, message["content"]))
    print()


def main():
    parser = argparse.ArgumentParser(description="Ask questions about the shop database.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list", action="store_true", help="show your conversations")
    group.add_argument("--last", action="store_true", help="continue your most recent conversation")
    group.add_argument("--continue", dest="conversation_id", type=int, metavar="ID",
                       help="continue the conversation with this id")
    parser.add_argument("--user", default="demo", help="whose conversations to use (default: demo)")
    args = parser.parse_args()

    if not check_connection():
        sys.exit("Cannot reach the database. Is it running? (docker compose up -d)")

    store = ConversationStore()
    conversations = store.list_conversations(args.user)  # newest first

    if args.list:
        print_conversations(conversations)
        return

    conversation_id = args.conversation_id
    if args.last:
        if not conversations:
            sys.exit("No conversations yet. Start one with: python chat.py")
        conversation_id = conversations[0]["id"]
    if conversation_id is not None:
        if conversation_id not in [c["id"] for c in conversations]:
            sys.exit("No conversation {}. See your conversations with: python chat.py --list".format(conversation_id))
        print("Continuing conversation {}.\n".format(conversation_id))
        print_recap(store, conversation_id)
    else:
        print("New conversation.\n")
    print('Ask a question about customers, products or orders. Type "exit" to quit.\n')

    agent = NLDBAgent(store=store)
    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):  # Ctrl-D or Ctrl-C
            print()
            break
        if question.lower() in ("exit", "quit"):
            break
        if not question:
            continue

        result = agent.ask(question, conversation_id=conversation_id, user_id=args.user)
        conversation_id = result["conversation_id"]  # set on the first question of a new chat

        print("\nAgent: {}".format(result["summary"]))
        if result["sql"]:
            print("\nSQL: {}".format(result["sql"]))
        if result["rows"]:
            print()
            print_table(result["columns"], result["rows"])
        if result["highlights"]:
            print("\nWorth noticing:")
            for highlight in result["highlights"]:
                print("  ! {}".format(highlight))
        if result["follow_ups"]:
            print("\nYou could ask next:")
            for follow_up in result["follow_ups"]:
                print("  - {}".format(follow_up))
        print()

    if conversation_id is not None:
        print("Saved. To come back to this chat: python chat.py --continue {}".format(conversation_id))


if __name__ == "__main__":
    main()
