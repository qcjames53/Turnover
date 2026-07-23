from ..db import Conversation, Message
from . import render_messages

_DEMO_CONVERSATION_A = Conversation(
    address="+14085551234",
    contact_name="Phil Schiller",
    messages=[
        Message(
            handle="3",
            folder="inbox",
            datetime="20070109T075000",
            sender_addressing="+15558675309",
            recipient_addressing="",
            text="Still on for dinner tonight?",
            local_read=True,
        ),
        Message(
            handle="4",
            folder="sent",
            datetime="20070109T075100",
            sender_addressing="",
            recipient_addressing="+15558675309",
            text="Absolutely",
            local_read=True,
        ),
        Message(
            handle="5",
            folder="inbox",
            datetime="20070109T081700",
            sender_addressing="+15558675309",
            recipient_addressing="",
            text="Your turn to pick",
            local_read=True,
        ),
        Message(
            handle="6",
            folder="sent",
            datetime="20070109T081800",
            sender_addressing="",
            recipient_addressing="+15558675309",
            text="Hmmm... Sushi place in Marin?",
            local_read=True,
        ),
        Message(
            handle="7",
            folder="inbox",
            datetime="20070109T082000",
            sender_addressing="+15558675309",
            recipient_addressing="",
            text="How about 7pm tonight?",
            local_read=True,
        ),
        Message(
            handle="8",
            folder="sent",
            datetime="20070109T101700",
            sender_addressing="",
            recipient_addressing="+15558675309",
            text="Sounds great! See you there.",
            local_read=True,
        ),
    ],
)

def run_onboarding_wizard(options: list | None = None) -> None:
    print(render_messages.get_conversation_string([_DEMO_CONVERSATION_A]))
