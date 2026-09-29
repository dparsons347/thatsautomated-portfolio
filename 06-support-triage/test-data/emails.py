"""The canned emails. Used three ways:

1. tests/test_graph.py runs all ten through the graph with a scripted model (wiring, gate, routing).
2. evals/live_eval.py runs them through the real model and prints category, confidence, route.
3. The n8n "P6: Seed test emails" workflow imports the Loom set (the ones marked loom=True) into Gmail.

Sender addresses are plus addresses of daniel@thatsautomated.com, so any reply we send lands in
an inbox we control. Three senders exist in HubSpot (see hubspot-seed.md); the rest are unknown.
"""

SALES_BODY = (
    "Hi, I run a 6 person landscaping company. Leads come in from our website form and from "
    "Facebook, and right now my office manager copies them into Jobber and then into QuickBooks by hand. "
    "Is that something you can automate? Roughly what does a project like that cost?\n\nMaya Brooks\nBrooks Outdoor Co."
)

SALES_REPLY_BODY = (
    "Hi Maya,\n\nThanks for the note. Getting form and Facebook leads into Jobber and QuickBooks without "
    "retyping is a good fit for what we do. A few questions: about how many leads a week, and which "
    "Jobber plan are you on?\n\nHere's a link for a 20 minute call: https://thatsautomated.com/contact\n\nDaniel\nThat's Automated"
)

EMAILS = [
    {
        "key": "sales_new", "loom": True,
        "from_email": "daniel+maya@thatsautomated.com", "from_name": "Maya Brooks",
        "subject": "Automating our lead entry",
        "body": SALES_BODY,
        "expect": {"category": "sales", "route": "draft"},
    },
    {
        "key": "support_login", "loom": True,
        "from_email": "daniel+priya@thatsautomated.com", "from_name": "Priya Raman",
        "subject": "Reminder texts stopped",
        "body": ("Hi Daniel, the appointment reminder workflow didn't send anything this morning. "
                 "There's a message in our Slack alerts channel saying the Google connection expired. "
                 "What do I need to do?\n\nPriya\nRaman Family Dental"),
        "expect": {"category": "support", "route": "draft"},
    },
    {
        "key": "existing_client", "loom": True,
        "from_email": "daniel+marcus@thatsautomated.com", "from_name": "Marcus Webb",
        "subject": "September invoice and the Opelika office",
        "body": ("Daniel, the September invoice came in about $400 over what I expected. Can you walk me "
                 "through it? Also we're opening a second office in Opelika next month and I want the "
                 "estimate workflow to cover it. Let's talk scope.\n\nMarcus\nWebb Roofing"),
        "expect": {"category": "existing_client", "route": "person"},
    },
    {
        "key": "vendor_pitch", "loom": True,
        "from_email": "daniel+growthlane@thatsautomated.com", "from_name": "Tyler at GrowthLane",
        "subject": "Guest post collaboration for thatsautomated.com",
        "body": ("Hi there, I'm Tyler from GrowthLane. We place high authority guest posts and backlinks "
                 "for agencies like yours. We could get That's Automated featured on 10 DA50+ sites this "
                 "month. Open to a quick chat about pricing?\n\nTyler"),
        "expect": {"category": "vendor", "route": "archive"},
    },
    {
        "key": "ambiguous", "loom": True,
        "from_email": "daniel+sam@thatsautomated.com", "from_name": "Sam",
        "subject": "Following up",
        "body": "Hey, just circling back on what we talked about the other day. Let me know.\n\nSam",
        "expect": {"category": "unclear", "route": "person"},
    },
    {
        "key": "angry_reply", "loom": False, "reply_to": "sales_new",
        "from_email": "daniel+maya@thatsautomated.com", "from_name": "Maya Brooks",
        "subject": "Re: Automating our lead entry",
        "body": ("I booked the call for 10am today and nobody showed up. I waited 20 minutes. "
                 "Honestly not a great first impression. Is anyone actually there?\n\nMaya"),
        "history": [
            {"from_email": "daniel+maya@thatsautomated.com", "body": SALES_BODY, "category": "sales", "direction": "inbound"},
            {"from_email": "daniel@thatsautomated.com", "body": SALES_REPLY_BODY, "direction": "outbound"},
        ],
        "prior_category": "sales",
        "expect": {"category": "existing_client|sales|unclear", "route": "person"},
    },
    {
        "key": "spam", "loom": False,
        "from_email": "daniel+mailadmin@thatsautomated.com", "from_name": "Mailbox Admin",
        "subject": "ACTION REQUIRED: mailbox storage full",
        "body": ("Your mailbox has exceeded its storage limit. Incoming messages will be deleted in 24 hours. "
                 "Verify your password here to restore service: http://mail-verify-portal.example/login"),
        "expect": {"category": "spam", "route": "archive"},
    },
    {
        # The borderline case for the Loom: a lead seller dressed as a buyer. The model usually
        # calls it sales at around 0.6 and says in its reason that it may be a vendor pitch.
        # With the threshold at 0.55 it gets a sales draft; at 0.75 it goes to a person.
        "key": "lead_seller", "loom": False,
        "from_email": "daniel+brightpath@thatsautomated.com", "from_name": "Anita Shah",
        "subject": "Interested in automation for our clients",
        "body": ("Hello, we are a lead generation company working with home service businesses. Several of our "
                 "clients need CRM automation and we are looking for an automation partner. Could you tell me your "
                 "rates and availability? We can also supply you with 10 to 15 qualified leads a month.\n\nAnita Shah\nBrightPath Leads"),
        "expect": {"category": "sales|vendor|unclear", "route": "person"},
    },
    {
        "key": "support_not_covered", "loom": False,
        "from_email": "daniel+priya@thatsautomated.com", "from_name": "Priya Raman",
        "subject": "Exporting last month's reminders",
        "body": ("Quick one: can I export a list of every reminder text that went out last month? "
                 "Our office manager wants it as a spreadsheet for an audit.\n\nPriya"),
        "expect": {"category": "support", "route": "person"},
    },
    {
        "key": "support_hours", "loom": False,
        "from_email": "daniel+priya@thatsautomated.com", "from_name": "Priya Raman",
        "subject": "Saturday coverage?",
        "body": ("Are you around on Saturdays if something breaks? We're open half days on Saturday and "
                 "I want to know who to call.\n\nPriya"),
        "expect": {"category": "support", "route": "draft"},
    },
]

BY_KEY = {e["key"]: e for e in EMAILS}
