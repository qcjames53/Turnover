from datetime import datetime, timedelta

from ..db import Conversation, Message

DEMO_CONVERSATION = Conversation(
    address="+14085551234",
    contact_name="Phil Schiller",
    messages=[
        Message(
            handle="3",
            folder="inbox",
            datetime="20070109T075000",
            text="Still on for dinner tonight?",
        ),
        Message(
            handle="4",
            folder="sent",
            datetime="20070109T075100",
            text="Absolutely",
        ),
        Message(
            handle="5",
            folder="inbox",
            datetime="20070109T081700",
            text="Your turn to pick",
        ),
        Message(
            handle="6",
            folder="sent",
            datetime="20070109T081800",
            text="Hmmm... Sushi place in Marin?",
        ),
        Message(
            handle="7",
            folder="inbox",
            datetime="20070109T082000",
            text="How about 7pm tonight?",
        ),
        Message(
            handle="8",
            folder="sent",
            datetime="20070109T101700",
            text="Sounds great! See you there.",
        ),
        Message(
            handle="9",
            folder="sent",
            datetime=datetime.today().strftime("%Y%m%dT094100") if datetime.today().hour >= 10 else (datetime.today() - timedelta(days=1)).strftime("%Y%m%dT094100"),
            text="Here's to the crazy ones. The misfits. The rebels. The troublemakers. The round pegs in the square holes. The ones who see things differently. They're not fond of rules. And they have no respect for the status quo. You can quote them, disagree with them, glorify or vilify them.\r\n\r\nAbout the only thing you can't do is ignore them."
        ),
        Message(
            handle="10",
            folder="sent",
            datetime=datetime.today().strftime("%Y%m%dT094100") if datetime.today().hour >= 10 else (datetime.today() - timedelta(days=1)).strftime("%Y%m%dT094100"),
            text="Because they change things. They push the human race forward. And while some may see them as the crazy ones, we see genius. Because the people who are crazy enough to think they can change the world, are the ones who do."
        ),
    ],
)
