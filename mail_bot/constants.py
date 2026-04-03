EMAIL_AGENT_PROMPT = """
<system>
You are a personal email assistant. Your job is to monitor the user's inbox, summarize unread emails, and help them focus on what matters most.

<response_format>
Every response MUST begin with a status line:
"You have [N] unread emails."

Then present emails grouped by priority tier:

🔴 URGENT — Needs action today
🟡 IMPORTANT — Needs action this week  
🟢 FYI — Read when you have time
⚪ LOW — Skippable or bulk/promotional

For each URGENT and IMPORTANT emails, include:
- Sender (name and/or address)
- Subject line
- One-sentence summary of the content and any action required
- Time received (relative, e.g. "2 hours ago")

For FYI and LOW emails:
- Number of emails in these categories
- One small paragraph summary of all the emails
</response_format>

<priority_rules>
Rank emails higher when they involve:
- Direct requests from real people (not automated/no-reply)
- Deadlines or time-sensitive actions (meetings, approvals, expiring offers)
- Replies in active threads the user is part of
- Financial matters (invoices, payments, billing issues)
- Messages from frequent or known-important contacts

Rank emails lower when they involve:
- Marketing, newsletters, or promotional content
- Automated notifications (build alerts, social media digests, shipping updates with no action needed)
- Bulk CC'd threads where the user is not directly addressed
- Spam or near-spam
</priority_rules>

<behavior>
- If the user asks to act on an email (reply, archive, snooze, flag), do so and confirm the action taken.
- If the user asks about a specific email, provide the full content rather than a summary.
- When drafting replies, match the tone and formality of the original sender.
- Never fabricate email content. If you cannot retrieve an email, say so.
- If inbox is empty, respond: "You have 0 unread emails. You're all caught up!"
</behavior>
</system>
"""

TEST_EMAILS = [
    {
        "id": "msg_001",
        "from": "jessica.chen@acmecorp.com",
        "to": "user@email.com",
        "subject": "Contract renewal — signature needed by EOD tomorrow",
        "body": "Hi,\n\nThe annual service contract with Pinnacle Ltd is up for renewal. Legal has reviewed and approved the updated terms. I need your signature on the attached document by end of day tomorrow (March 31) or we risk a lapse in coverage.\n\nCan you confirm you've received this? Happy to jump on a call if you have questions.\n\nThanks,\nJessica Chen\nAccount Manager, Acme Corp",
        "timestamp": "2026-03-30T08:14:00Z",
        "read": "false",
    },
    {
        "id": "msg_002",
        "from": "daniel.morris@email.com",
        "to": "user@email.com",
        "subject": "Re: Q2 budget planning — updated numbers",
        "body": "Hey,\n\nAttached is the revised Q2 budget with the changes we discussed Friday. Main differences: marketing allocation is up 12%, and we cut the consulting line item by $15k.\n\nLet me know if this looks good and I'll send it to finance before Thursday's review meeting.\n\nCheers,\nDaniel",
        "timestamp": "2026-03-30T07:42:00Z",
        "read": "false",
    },
    {
        "id": "msg_003",
        "from": "noreply@github.com",
        "to": "user@email.com",
        "subject": "[backend-api] PR #482 merged: Fix rate limiter edge case",
        "body": "The following pull request has been merged into main:\n\nPR #482: Fix rate limiter edge case on concurrent requests\nAuthor: sara-k\nReviewers: user, jt-dev\nFiles changed: 3\n\nView on GitHub: https://github.com/org/backend-api/pull/482",
        "timestamp": "2026-03-30T06:58:00Z",
        "read": "false",
    },
    {
        "id": "msg_004",
        "from": "offers@shopdaily.com",
        "to": "user@email.com",
        "subject": "🎉 Flash Sale — 40% off everything today only!",
        "body": "FLASH SALE IS HERE!\n\nFor today only, enjoy 40% off sitewide. No code needed — discount applied at checkout.\n\nShop now: https://shopdaily.com/sale\n\nFree shipping on orders over $50. Don't miss out!\n\nUnsubscribe: https://shopdaily.com/unsub",
        "timestamp": "2026-03-30T05:00:00Z",
        "read": "false",
    },
    {
        "id": "msg_005",
        "from": "maria.gonzalez@email.com",
        "to": "user@email.com",
        "subject": "Lunch Wednesday?",
        "body": "Hey! It's been a while. Are you free for lunch this Wednesday? I was thinking that new Thai place on 5th. Let me know!\n\n- Maria",
        "timestamp": "2026-03-29T22:15:00Z",
        "read": "false",
    },
]
