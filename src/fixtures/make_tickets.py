"""Deterministic golden-set generator (docs/HARNESS_SPEC.md §1, GOALS.md § G2).

Gold is decided first (bucket, split, labels, expected outcome); the ticket text is then rendered from it (I-2).
Clean, pii, duplicate and malformed tickets are composed from the phrase banks below. Hard and injection tickets
are hand-authored in hard_cases.json. Same seed -> byte-identical files.

    python3 -m src.fixtures.make_tickets           # write evals/gold/, evals/inputs/manifest.csv, README label stats
    python3 -m src.fixtures.make_tickets --check   # regenerate into a temp dir and diff against the repo files
"""
from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import random
import re
import shutil
import sys
import tempfile
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.common.norm import content_sha256, dedupe_key

SEED = 20261012
VERSION = "1.0"
ROOT = Path(__file__).resolve().parents[2]
HARD_CASES = Path(__file__).resolve().with_name("hard_cases.json")
GOLD_DIR = "evals/gold"
MANIFEST = "evals/inputs/manifest.csv"
README = "evals/README.md"
MANIFEST_HEADER = ["input_id", "split", "label_bucket", "category", "priority", "urgency", "expect_outcome",
                   "gold_path"]
STATS_START = "<!-- label-stats:start (written by src/fixtures/make_tickets.py; do not edit by hand) -->"
STATS_END = "<!-- label-stats:end -->"

CATEGORIES = ("billing", "access", "bug", "outage", "howto", "feature", "privacy", "other")
PRIORITIES = ("P1", "P2", "P3", "P4")
URGENCIES = ("high", "medium", "low")
OUTCOMES = ("auto_route", "review", "duplicate_skip", "rejected")
BUCKETS = (("clean", 104), ("hard", 48), ("injection", 16), ("pii", 12), ("duplicate", 12), ("malformed", 8))
HARD_KINDS = ("ambiguous", "multi_issue", "tone_mismatch", "short", "thread_quoted", "auto_reply")
ALWAYS_REVIEW = ("privacy", "other")
PRIVACY_KEYWORDS = ("gdpr", "ccpa", "delete my data", "data subject", "right to access")  # ARCHITECTURE C-14 R4
MAX_BODY_CHARS = 20000      # ARCHITECTURE §5.2 max_body_chars
MAX_SUBJECT_CHARS = 300     # C-2
MAX_ATTACHMENTS = 10        # C-2
MAX_MODEL_CHARS = 6000      # §5.2 max_model_chars
MIN_CLEAN_WORDS, MAX_CLEAN_WORDS = 40, 250  # HARNESS_SPEC §1.1 clean bucket
FAULTS_TEST = ((("jira", "commit_then_504"), 3), (("jira", "503"), 2), (("slack", "503"), 2),
               (("sink:jira_links", "503"), 2))
AGENT = "Sam Ortega"
BASE_TIME = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# ---------------------------------------------------------------- writers (fictional)
FIRST_NAMES = ("Dana", "Priya", "Marco", "Ingrid", "Tomasz", "Aisha", "Kenji", "Lucia", "Owen", "Sofia", "Jonas",
               "Fatima", "Elliot", "Mei", "Rafael", "Hanna", "Darius", "Chloe", "Mateo", "Freya", "Nikhil", "Amara",
               "Lars", "Zoe", "Bruno", "Leila", "Henrik", "Yara")
LAST_NAMES = ("Whitfield", "Okonkwo", "Lindqvist", "Moreau", "Castellano", "Brandt", "Novak", "Haddad", "Ferreira",
              "Kowalczyk", "Tanabe", "Delacroix", "Albright", "Varga", "Esposito", "Rasmussen", "Quintero",
              "Halloran", "Szabo", "Pemberton", "Achterberg", "Iversen", "Marchetti", "Oyelaran")
COMPANIES = (  # name, mail slug, tld, region
    ("Larkspur Labs", "larkspurlabs", "com", "US"), ("Quillmoor GmbH", "quillmoor", "org", "EU"),
    ("Tidewell Logistics", "tidewell", "com", "US"), ("Brambleway Studio", "brambleway", "net", "EU"),
    ("Ottervale Software", "ottervale", "com", "US"), ("Glimmerbrook BV", "glimmerbrook", "org", "EU"),
    ("Saltmarsh Robotics", "saltmarsh", "com", "US"), ("Kettlewick Ltd", "kettlewick", "net", "EU"),
    ("Fennimore Freight", "fennimore", "com", "US"), ("Amberlow AB", "amberlow", "org", "EU"),
    ("Velloran SAS", "velloran", "net", "EU"), ("Hollowfen Media", "hollowfen", "com", "US"),
    ("Wrenfield Partners", "wrenfield", "com", "US"), ("Nimbleford Dental", "nimbleford", "org", "US"),
)
ROLES = ("operations manager", "office manager", "head of finance", "IT lead", "customer success lead", "founder",
         "marketing coordinator", "engineering manager", "support lead", "account manager", "project manager")
CITIES = {"US": ("Austin", "Denver", "Boston", "Chicago", "Portland", "Atlanta"),
          "EU": ("Berlin", "Lisbon", "Dublin", "Amsterdam", "Lyon", "Stockholm", "Madrid")}

# ---------------------------------------------------------------- composition banks
GREETINGS = {"neutral": ("Hi,", "Hello,", "Hi team,", "Hello support,"),
             "friendly": ("Hi there!", "Hey team,", "Hi folks,"),
             "formal": ("Dear Support Team,", "Good morning,", "Dear support,"),
             "frustrated": ("Hi,", "Hello,")}
CLOSINGS = {"neutral": ("Thanks,", "Best,", "Regards,"),
            "friendly": ("Thanks so much!", "Cheers,", "Many thanks,"),
            "formal": ("Kind regards,", "Best regards,", "Yours sincerely,"),
            "frustrated": ("Thanks,", "Regards,")}
INTROS = ("I'm the {role} at {company}.", "Writing on behalf of {company}.", "I look after our account at {company}.")
FRUSTRATED = ("Honestly, this is really frustrating.", "This has already cost us a morning of work.",
              "We are not happy that this happened at all.")
URGENCY_PHRASES = {
    "high": ("This is blocking us right now, so we need help today.",
             "We have a hard deadline tomorrow morning, so please treat this as urgent.",
             "It is affecting our work as we speak, so please look at it today."),
    "medium": ("Could you look into this sometime this week?", "We would like this sorted before the end of the week.",
               "A reply in the next few days would be great."),
    "low": ("No rush on this, whenever you have a moment.", "There is no deadline here.", "Not urgent at all."),
}
URGENCY_WHY = {"high": "ongoing impact or a deadline within 24 h", "medium": "action needed this week",
               "low": "no time pressure"}

# Each scenario fixes category and priority; urgency is drawn from the allowed list and rendered as a phrase.
SCENARIOS = {
    "billing": [
        {"id": "billing-double-charge", "priority": "P2", "urgency": ["high", "medium"],
         "why": "a double charge is P2 in the guide",
         "subjects": ["Charged twice this month", "Double charge on our {plan} plan", "Duplicate payment for invoice {inv}"],
         "issue": ["We were charged twice for our {plan} subscription this month: two payments of {amount} went through on {weekday}, a few minutes apart.",
                   "Our card statement shows the {plan} plan renewal of {amount} twice on {weekday}, but we only have one workspace and one subscription."],
         "details": ["Invoice {inv} only lists one payment, so the second charge looks like a mistake.",
                     "Our finance team flagged it during the weekly reconciliation.",
                     "The second charge has pushed our company card close to its monthly limit."],
         "ask": ["Please refund the duplicate payment and confirm once it is done.",
                 "Could you reverse the second charge and send a corrected receipt?"]},
        {"id": "billing-invoice-seats", "priority": "P3", "urgency": ["medium", "low"],
         "why": "a single invoice error is P3",
         "subjects": ["Invoice {inv} has the wrong seat count", "Wrong number of seats billed", "Question about invoice {inv}"],
         "issue": ["Invoice {inv} bills us for {seats_hi} seats, but we only have {seats} active users in the workspace.",
                   "Our {month} invoice charges for {seats_hi} seats although we removed several users last month and now have {seats}."],
         "details": ["The members page in the admin area also shows {seats} users.",
                     "We paid the invoice already so our books stay clean, but we expect a credit for the difference."],
         "ask": ["Please send a corrected invoice or a credit note.", "Could you check the seat count and adjust the next invoice?"]},
        {"id": "billing-vat-missing", "priority": "P3", "urgency": ["medium", "high"],
         "why": "a single invoice error is P3",
         "subjects": ["VAT ID missing on invoice", "Invoice needs our VAT number", "Tax details wrong on invoice {inv}"],
         "issue": ["Our VAT ID is saved in the billing settings, but it does not appear on invoice {inv}, and the invoice charges VAT that should be reverse charged.",
                   "Invoice {inv} shows no VAT ID for {company} and adds VAT at the full rate, although we are a registered business in the EU."],
         "details": ["Our accountant cannot book the invoice in its current form.",
                     "We checked the billing settings and the tax details look correct there."],
         "ask": ["Could you reissue the invoice with the VAT ID and a reverse charge note?", "Please send a corrected invoice we can book."]},
        {"id": "billing-downgrade-credit", "priority": "P3", "urgency": ["medium", "low"],
         "why": "a billing error with no work blocked is P3",
         "subjects": ["Credit after downgrade", "Prorated refund for plan change", "Downgrade not reflected on our bill"],
         "issue": ["We downgraded from the Business plan to the {plan_low} plan in the middle of the billing cycle, and the latest invoice still charges the full Business price of {amount}.",
                   "After switching down to the {plan_low} plan, we expected a prorated credit, but invoice {inv} shows the old Business plan price."],
         "details": ["The plan page in the settings shows the new plan correctly.", "Your pricing page says plan changes are prorated."],
         "ask": ["Can you apply the prorated credit to our next invoice?", "Please refund the difference or credit our account."]},
        {"id": "billing-cancel", "priority": "P3", "urgency": ["medium", "low"],
         "why": "cancellation intent is billing; nothing is broken, so P3",
         "subjects": ["Cancel our subscription", "Please cancel at the end of the term", "Cancellation request for {company}"],
         "issue": ["We have decided to cancel our {plan} subscription at the end of the current billing period.",
                   "Please cancel the {company} subscription when the current term ends; we are consolidating our software."],
         "details": ["We do not want the plan to renew automatically.", "Please make sure no further charges are made after this term.",
                     "We will export our projects ourselves before the end date."],
         "ask": ["Please confirm the cancellation date in writing.", "Could you confirm the last charge we should expect?"]},
        {"id": "billing-card-declined", "priority": "P2", "urgency": ["high"],
         "why": "a failed renewal with suspension pending blocks the whole account with no workaround, so P2",
         "subjects": ["Renewal payment failed", "Card declined, account at risk of suspension", "Payment failed for {plan} renewal"],
         "issue": ["Our renewal payment of {amount} failed, and the dashboard now says the workspace will be suspended in two days.",
                   "The card payment for our {plan} renewal was declined, and we got a warning that access will be suspended."],
         "details": ["Our bank says it never saw the payment attempt, so we think the problem is on the payment side.",
                     "We already updated the card details once and the retry failed again."],
         "ask": ["Please stop the suspension while we sort out the payment.",
                 "Can you send a payment link or let us pay by bank transfer instead?"]},
        {"id": "billing-annual-question", "priority": "P4", "urgency": ["low"],
         "why": "a general billing question with no impact is P4",
         "subjects": ["Switching to annual billing", "Monthly to yearly billing", "Question about annual plans"],
         "issue": ["We are on monthly billing for the {plan} plan and would like to switch to annual billing at the next renewal.",
                   "Is there a discount if we move our {plan} subscription from monthly to annual billing?"],
         "details": ["Nothing is wrong, we are just planning next year's budget.", "We have {seats} users and do not expect that to change much."],
         "ask": ["Could you tell us how the switch works and what the annual price would be?", "Please let us know the steps."]},
    ],
    "access": [
        {"id": "access-locked-admin", "priority": "P2", "urgency": ["high"],
         "why": "a locked-out admin is P2 in the guide",
         "subjects": ["Locked out of admin account", "Admin locked out after 2FA attempts", "Cannot sign in as workspace admin"],
         "issue": ["I am the only admin on our workspace and I am locked out after too many failed two-factor codes.",
                   "My admin account got locked after several 2FA attempts, and I am the only person at {company} who can manage users."],
         "details": ["My authenticator app shows codes, but the login page says they are invalid.",
                     "The account recovery page sends me in a loop back to the 2FA screen.",
                     "Nobody else on our side can add or remove users until this is fixed."],
         "ask": ["Please unlock the account or tell us how to verify ownership.", "Can you help me get back in?"]},
        {"id": "access-reset-email", "priority": "P3", "urgency": ["medium", "high"],
         "why": "one user cannot sign in on the web but still has the mobile app, so P3",
         "subjects": ["Password reset email never arrives", "No reset email", "Cannot reset my password"],
         "issue": ["I requested a password reset four times this morning, but the email never arrives.",
                   "The password reset link is not coming through to my inbox, and I have checked the spam folder."],
         "details": ["Colleagues on the same email domain receive your emails fine.",
                     "I can still use the mobile app because I am signed in there, so I am not completely stuck."],
         "ask": ["Could you check whether the reset emails are being sent?", "Please send a reset link or reset it from your side."]},
        {"id": "access-invite-expired", "priority": "P3", "urgency": ["medium"],
         "why": "an invitation problem for one new user is P3",
         "subjects": ["Invite link expired", "New colleague cannot join the workspace", "Invitation not working"],
         "issue": ["We invited a new colleague yesterday, but the invite link says it has expired when they open it.",
                   "Our new hire cannot join the workspace: every invitation we send shows an 'invitation expired' page."],
         "details": ["We have resent the invite three times with the same result.", "We have free seats on our plan, so that should not be the problem."],
         "ask": ["Can you check what is wrong with the invitations?", "Please help us get them into the workspace."]},
        {"id": "access-role-permission", "priority": "P3", "urgency": ["medium", "low"],
         "why": "a role problem for one user with others unaffected is P3",
         "subjects": ["Manager role cannot see Reports", "Permission problem for a team lead", "Role does not give access to Reports"],
         "issue": ["A team lead at {company} has the Manager role, but the Reports tab does not appear for them at all.",
                   "We gave one of our team leads the Manager role, and they still get a 'no permission' message when opening Reports."],
         "details": ["Other managers in the same workspace can see Reports.", "We tried removing and adding the role again."],
         "ask": ["Could you check their permissions?", "Please tell us what we are missing."]},
        {"id": "access-new-phone", "priority": "P2", "urgency": ["high"],
         "why": "the on-call engineer cannot sign in and has no other way to see alerts, so P2",
         "subjects": ["Lost my 2FA device", "New phone, cannot log in", "Two-factor codes lost after phone change"],
         "issue": ["I replaced my phone over the weekend and lost my authenticator app, so I cannot sign in anymore.",
                   "After a phone change my two-factor codes are gone, and the login page will not let me in."],
         "details": ["I am our on-call engineer this week, and I cannot see any alerts without signing in.",
                     "I do not have my backup codes with me, and our admin does not know how to reset it."],
         "ask": ["Can you reset the two-factor setup on my account?", "Please help me verify my identity and get back in."]},
        {"id": "access-suspicious-login", "priority": "P1", "urgency": ["high"],
         "why": "a suspected security incident is P1 in the guide",
         "subjects": ["Unknown login to our admin account", "Possible account takeover", "Suspicious sign-in and new API key"],
         "issue": ["We got sign-in alerts from a country where nobody at {company} works, and a new API key was created on our admin account that none of us made.",
                   "Someone signed in to our admin account overnight from an unknown location and created two API keys we do not recognise."],
         "details": ["We have changed the admin password, but we are not sure the other sessions were ended.",
                     "The audit log shows the new keys were used a few minutes later."],
         "ask": ["Please help us revoke all sessions and keys and check what was accessed.",
                 "Can your team investigate and lock this down with us?"]},
        {"id": "access-seat-limit", "priority": "P3", "urgency": ["medium"],
         "why": "a seat problem that blocks one new user is P3",
         "subjects": ["'Seat limit reached' when adding a user", "Cannot add users after buying seats", "New seats not available"],
         "issue": ["We bought five extra seats yesterday, but adding a new user still fails with 'seat limit reached'.",
                   "The admin page says we have {seats_hi} seats, yet inviting anyone new shows a seat limit error."],
         "details": ["The purchase shows on our invoice.", "We have {seats} people in the workspace right now."],
         "ask": ["Can you refresh our seat count?", "Please check why the new seats are not available."]},
    ],
    "bug": [
        {"id": "bug-export-csv", "priority": "P3", "urgency": ["medium", "low"],
         "why": "impaired with a workaround is P3",
         "subjects": ["CSV export stops at 1,000 rows", "Export missing rows", "Contacts export incomplete"],
         "issue": ["When I export the Contacts list to CSV, the file stops at exactly 1,000 rows, although we have about {n} contacts.",
                   "Our contacts CSV export is cut off at 1,000 rows every time."],
         "details": ["We can work around it by exporting in smaller filtered batches, but it takes a long time.",
                     "This started after last week's release; it worked before."],
         "ask": ["Could you look into it?", "Please let us know when a fix is planned."]},
        {"id": "bug-chart-duplicate", "priority": "P3", "urgency": ["low", "medium"],
         "why": "a display error while the correct data is still available is P3",
         "subjects": ["Weekly chart shows Sunday twice", "Dashboard chart wrong", "Duplicate day in the weekly chart"],
         "issue": ["The weekly activity chart on our dashboard shows Sunday's numbers twice, and Monday is missing.",
                   "On the dashboard, the weekly chart repeats the Sunday bar and drops Monday."],
         "details": ["The raw numbers in the table below the chart are correct.", "I see it in both Chrome and Firefox."],
         "ask": ["Could you take a look?", "Is this a known issue?"]},
        {"id": "bug-integration-sync", "priority": "P2", "urgency": ["high", "medium"],
         "why": "a core workflow is broken for one customer with no workaround, so P2",
         "subjects": ["Webhook integration stopped sending events", "CRM sync broken since the update", "No events reaching our CRM"],
         "issue": ["Since Tuesday's update, our webhook integration has stopped sending deal events to our CRM.",
                   "Our CRM sync stopped working after your last release: no new events have arrived since then."],
         "details": ["The webhook settings still show the endpoint as active, and the test button returns success.",
                     "Our sales team depends on this sync, and we have no other way to move the data."],
         "ask": ["Please investigate as soon as possible.", "Can you check the delivery logs for our workspace?"]},
        {"id": "bug-save-error", "priority": "P2", "urgency": ["high"],
         "why": "a core workflow is broken for one customer with no workaround, so P2",
         "subjects": ["Template changes not saving", "Error when saving a project template", "'Something went wrong' on save"],
         "issue": ["Every time I edit a project template and press Save, I get 'Something went wrong' and the change is lost.",
                   "Saving any change to our project templates fails with a generic error, and the edits disappear."],
         "details": ["Our onboarding process is built on these templates, and there is no other way to edit them.",
                     "I tried a different browser and a private window with the same result."],
         "ask": ["Please help us fix this quickly.", "Could you look at this today?"]},
        {"id": "bug-timezone", "priority": "P3", "urgency": ["medium", "low"],
         "why": "impaired with a workaround is P3",
         "subjects": ["Scheduled reports arrive an hour late", "Timezone wrong after the clock change", "Report schedule off by one hour"],
         "issue": ["Since the daylight saving change, our scheduled reports arrive an hour later than the time we set.",
                   "Our 8:00 reports now come at 9:00, which started right after the clocks changed."],
         "details": ["The workspace timezone setting is correct.", "We can send the reports by hand in the meantime."],
         "ask": ["Could you check the scheduler?", "Please let us know if we need to change anything."]},
        {"id": "bug-upload-large", "priority": "P3", "urgency": ["medium"],
         "why": "impaired with a workaround is P3",
         "subjects": ["PDF upload fails at 99%", "Large file uploads failing", "Cannot upload files over 10 MB"],
         "issue": ["Uploading PDF files larger than about 10 MB fails at 99% with 'upload error'.",
                   "Any PDF above roughly 10 MB stops at 99% and then shows an upload error."],
         "details": ["Smaller files upload fine, so we split the large ones for now.", "Your docs say the limit is 50 MB on our plan."],
         "ask": ["Could you check what is going wrong?", "Is there a fix planned?"]},
        {"id": "bug-ios-crash", "priority": "P2", "urgency": ["high", "medium"],
         "why": "a core workflow is broken for one customer with no workaround (field staff use only the iOS app), so P2",
         "subjects": ["iOS app crashes on Inbox", "Mobile app crash", "App closes when opening Inbox"],
         "issue": ["The iOS app crashes every time I open the Inbox tab.", "On my iPhone, the app closes straight away when I tap Inbox."],
         "details": ["Our field technicians only use the iOS app, so they cannot see their new jobs.",
                     "We reinstalled the app and restarted the phones."],
         "ask": ["Could you look into it?", "Let me know if you need logs."]},
    ],
    "outage": [
        {"id": "outage-all-500", "priority": "P1", "urgency": ["high"],
         "why": "the API is down across all workspaces, which is outage material and P1",
         "subjects": ["All API calls returning 500", "API down for all our workspaces", "500 errors on every request"],
         "issue": ["Since {time}, every call to your API returns a 500 error, across all of our workspaces.",
                   "All of our API requests have failed with HTTP 500 since {time}, for every workspace and every API key we have."],
         "details": ["Our integrations and the customer-facing parts of our product are down because of this.",
                     "Your status page still shows everything as operational."],
         "ask": ["Please confirm you are aware and give us an estimate.", "Can you tell us what is happening?"]},
        {"id": "outage-app-blank", "priority": "P1", "urgency": ["high"],
         "why": "the app is down for many users at several companies, so outage P1",
         "subjects": ["App not loading for anyone", "Dashboard blank for the whole company", "Nobody can load the app"],
         "issue": ["The app does not load for anyone at {company}: we get a blank page and a spinner that never ends.",
                   "Since {time}, nobody in our {city1} and {city2} offices can load the dashboard."],
         "details": ["Contacts at two other companies tell us they see the same thing.", "We tried different networks and browsers."],
         "ask": ["Please let us know when it is back.", "Is there an incident on your side?"]},
        {"id": "outage-webhooks-delayed", "priority": "P2", "urgency": ["high"],
         "why": "a degraded service for many customers that is not fully down is P2",
         "subjects": ["Webhook deliveries delayed for hours", "All webhooks delayed", "Event delivery backlog"],
         "issue": ["Webhook deliveries have been delayed by more than an hour for all our workspaces since {time}.",
                   "Every webhook from your platform has arrived over an hour late since {time}, across all our accounts."],
         "details": ["Other customers in your community forum report the same delays.", "Nothing is lost so far, but everything downstream is late."],
         "ask": ["Please give us an update.", "When do you expect the backlog to clear?"]},
        {"id": "outage-emails", "priority": "P1", "urgency": ["high"],
         "why": "a core service is down for many customers, so outage P1",
         "subjects": ["No notification emails being sent", "Email notifications down", "Emails stopped going out"],
         "issue": ["No notification emails have gone out from any of our workspaces since {time}, so our customers are not getting their receipts.",
                   "Since {time}, none of the system emails from your platform are being delivered, for any of our users."],
         "details": ["Two other companies we work with see the same problem.", "The email log in the admin area is empty for today."],
         "ask": ["Please treat this as an incident.", "Can you confirm the cause?"]},
        {"id": "outage-eu-region", "priority": "P1", "urgency": ["high"],
         "why": "a whole region is unreachable, so outage P1",
         "subjects": ["EU region down", "Cannot reach our EU workspaces", "EU data center timeouts"],
         "issue": ["Your EU region seems to be down: every request to our EU workspaces times out for our whole team in {city1} and {city2}.",
                   "All our workspaces hosted in the EU region have been unreachable since {time}."],
         "details": ["Our US workspace still works.", "We see the same from home connections and from our office."],
         "ask": ["Please confirm and let us know the expected recovery time.", "Is there an incident open?"]},
        {"id": "outage-search-down", "priority": "P2", "urgency": ["high"],
         "why": "a core feature is down for many customers while the rest of the app works, so P2",
         "subjects": ["Search returns nothing for everyone", "Search broken across accounts", "Global search down"],
         "issue": ["Search has returned no results for everyone in our account since {time}, and a contact at another company sees the same.",
                   "Global search stopped working for all our users at {time}; every query returns zero results."],
         "details": ["Everything else in the app works, so we can still browse by hand.", "Clearing caches did not help."],
         "ask": ["Please let us know when it will be fixed.", "Is this a known incident?"]},
        {"id": "outage-slow", "priority": "P2", "urgency": ["high"],
         "why": "the whole service is degraded for many users but still usable, so P2",
         "subjects": ["Whole app extremely slow", "Performance problem for all users", "Pages take 30+ seconds"],
         "issue": ["Since {time} the whole app has been extremely slow for everyone at {company}: pages take more than 30 seconds to load.",
                   "Everything in the app has been crawling since {time}, for all our users in {city1} and {city2}."],
         "details": ["People at other companies are posting about the same thing.", "We can still work, but very slowly."],
         "ask": ["Please look into it.", "Can you share an update?"]},
    ],
    "howto": [
        {"id": "howto-schedule-report", "priority": "P4", "urgency": ["low"],
         "why": "a how-to question that does not block work is P4",
         "subjects": ["How to schedule a weekly report", "Emailing reports automatically", "Weekly report by email"],
         "issue": ["How do I schedule a weekly report so that it is emailed to my manager every Monday?",
                   "Is there a way to send the activity report automatically by email each week?"],
         "details": ["I found the Reports page but not the schedule option.", "We are on the {plan} plan, if that matters."],
         "ask": ["A link to the right help article would be great.", "Thanks for any pointers."]},
        {"id": "howto-api-rate-limit", "priority": "P3", "urgency": ["medium"],
         "why": "a how-to that blocks work is P3",
         "subjects": ["API rate limits on our plan", "How to avoid 429 errors", "Rate limit question"],
         "issue": ["Our nightly sync job is hitting 429 responses, and I need to know the API rate limits for the {plan} plan so we can pace the requests.",
                   "What are the API rate limits for our plan? Our sync stops halfway with 429 responses."],
         "details": ["The job is blocked until we know how to pace it.", "I could not find the limits in the API reference."],
         "ask": ["Could you share the limits and the recommended retry approach?", "Please point me to the right page."]},
        {"id": "howto-custom-field", "priority": "P4", "urgency": ["low"],
         "why": "a how-to question about an existing feature with no impact is P4",
         "subjects": ["Adding a custom field", "Custom field on the contact form", "How to add extra fields"],
         "issue": ["Is there a way to add a custom field, like 'contract end date', to the contact form?",
                   "How can I add our own field to contact records?"],
         "details": ["I saw a mention of custom fields in your changelog.", "We would use it for renewal tracking."],
         "ask": ["Thanks in advance.", "Any help is appreciated."]},
        {"id": "howto-sso-setup", "priority": "P3", "urgency": ["medium"],
         "why": "a configuration question that blocks a planned rollout is P3",
         "subjects": ["Setting up SAML SSO", "SSO configuration question", "Which attribute for email in SAML"],
         "issue": ["We are setting up SAML single sign-on with our identity provider. Which attribute should carry the user's email address?",
                   "We are configuring SSO for {company} and are not sure how to map the SAML attributes."],
         "details": ["We want to switch everyone over before the end of the month.",
                     "Nothing is broken; we just want to get the setup right the first time."],
         "ask": ["Could you send the attribute mapping we need?", "A setup guide would help."]},
        {"id": "howto-bulk-import", "priority": "P3", "urgency": ["medium", "high"],
         "why": "a how-to that blocks the start of work is P3",
         "subjects": ["Bulk import of contacts", "Importing contacts from a spreadsheet", "How to import {n} contacts"],
         "issue": ["How do I bulk-import about {n} contacts from a spreadsheet?",
                   "What is the best way to import our existing contact list of roughly {n} rows?"],
         "details": ["Our team starts using the app properly once the data is in.", "The file has name, company and city columns."],
         "ask": ["Please tell us the steps or the template to use.", "Is there a template file?"]},
        {"id": "howto-roles-docs", "priority": "P4", "urgency": ["low"],
         "why": "a docs question with no impact is P4",
         "subjects": ["What can each role see?", "Role documentation", "Question about roles"],
         "issue": ["Where in the docs can I find what each role (Member, Manager, Admin) can see and do?",
                   "Is there an overview of the permissions for each user role?"],
         "details": ["We are reviewing who has which role.", "We are just tidying up our workspace."],
         "ask": ["A link would be enough.", "Thanks!"]},
        {"id": "howto-slack-connect", "priority": "P4", "urgency": ["low", "medium"],
         "why": "a how-to question about an existing integration with no impact is P4",
         "subjects": ["Posting new tasks to a Slack channel", "Connecting to Slack", "Slack notifications setup"],
         "issue": ["Can I connect the app to our Slack workspace so new tasks post in a channel?",
                   "How do we set up Slack notifications for new tasks in one project?"],
         "details": ["I saw a Slack option under Integrations, but it asks for settings I do not understand.",
                     "We only want one channel, not all projects."],
         "ask": ["Could you explain the steps?", "Thanks in advance."]},
    ],
    "feature": [
        {"id": "feature-dark-mode", "priority": "P4", "urgency": ["low"],
         "why": "a request for something the product does not do is P4",
         "subjects": ["Dark mode please", "Feature request: dark theme", "Any plans for dark mode?"],
         "issue": ["It would be great to have a dark mode in the web app.", "Could you add a dark theme? Many of us work late."],
         "details": ["Several people on our team have asked for it.", "The mobile app already has one, so the web app feels inconsistent.",
                     "A browser extension works for some pages, but it breaks the charts."],
         "ask": ["Please add it to the roadmap.", "Let us know if it is planned."]},
        {"id": "feature-gantt", "priority": "P4", "urgency": ["low", "medium"],
         "why": "a request for something the product does not do is P4",
         "subjects": ["Gantt view request", "Timeline view for projects", "Feature idea: Gantt charts"],
         "issue": ["We would love a Gantt or timeline view for projects, with dependencies between tasks.",
                   "Please consider adding a Gantt chart view; we plan long projects with many steps."],
         "details": ["Right now we export to a spreadsheet to see the timeline.", "This would help us present plans to clients.",
                     "Most of our projects run for six months or more."],
         "ask": ["Is this on your roadmap?", "Please pass this on to your product team."]},
        {"id": "feature-bulk-delete-api", "priority": "P4", "urgency": ["medium", "low"],
         "why": "a request for something the product does not do is P4",
         "subjects": ["API endpoint for bulk delete", "Feature request: bulk delete via the API", "Bulk operations in the API"],
         "issue": ["Your API lets us delete records one at a time, but we need a bulk delete endpoint for cleanup jobs.",
                   "Could you add a bulk delete endpoint to the API?"],
         "details": ["Deleting 5,000 records one by one takes hours.", "Our developers would use it every month.",
                     "A bulk endpoint would also mean far fewer requests against your API."],
         "ask": ["Please let us know if this is planned.", "Is there a timeline for this?"]},
        {"id": "feature-granular-roles", "priority": "P4", "urgency": ["low"],
         "why": "a request for something the product does not do is P4",
         "subjects": ["More granular roles", "Custom roles request", "Feature request: custom permissions"],
         "issue": ["We would like to define our own roles, for example someone who can edit projects but not see billing.",
                   "Please add custom roles with permissions we can choose ourselves."],
         "details": ["The three fixed roles do not fit how our agency works.", "Our contractors currently see more than they need.",
                     "Other apps we use let us copy a role and change a few settings."],
         "ask": ["Please consider it for a future release.", "Thanks for listening."]},
        {"id": "feature-xlsx-export", "priority": "P4", "urgency": ["low"],
         "why": "a request for something the product does not do is P4",
         "subjects": ["Export to Excel format", "XLSX export request", "Feature request: Excel export"],
         "issue": ["Could you add an export to XLSX next to the CSV export?", "We would like reports to export straight to Excel format."],
         "details": ["Our finance team re-formats every CSV by hand.", "Number formats get lost in CSV.",
                     "Dates also turn into text when we open the CSV files."],
         "ask": ["It would save us a lot of time.", "Please add it to the list."]},
        {"id": "feature-outlook-sync", "priority": "P4", "urgency": ["medium", "low"],
         "why": "a request for something the product does not do is P4",
         "subjects": ["Outlook calendar sync", "Feature request: Outlook integration", "Two-way calendar sync"],
         "issue": ["Please add two-way sync with Outlook calendars; today only Google Calendar is supported.",
                   "Could you support Outlook calendar sync? Most of our company is on Microsoft 365."],
         "details": ["We are deciding whether to roll the app out to more teams this quarter.", "People currently copy meetings by hand.",
                     "Meetings that are moved in Outlook are often missed in the app."],
         "ask": ["Is this on the roadmap?", "Please let us know if it is planned."]},
        {"id": "feature-multi-currency", "priority": "P4", "urgency": ["low"],
         "why": "a request for something the product does not do is P4",
         "subjects": ["Multi-currency support", "Feature request: deals in EUR and USD", "More currencies"],
         "issue": ["We would like to keep deals in more than one currency in the same workspace.",
                   "Could you support several currencies per workspace?"],
         "details": ["We sell in the US and in Europe.", "Right now we keep two separate workspaces.",
                     "Our reports would need to convert amounts at a fixed monthly rate."],
         "ask": ["Please consider it.", "Thanks for considering it."]},
    ],
    "privacy": [
        {"id": "privacy-dsar-access", "priority": "P3", "urgency": ["medium"], "intro": False,
         "why": "a data access request is privacy; the legal deadline is weeks away, so P3",
         "subjects": ["Data access request", "Request for a copy of my personal data", "Subject access request"],
         "issue": ["Under GDPR Article 15, I request a copy of all personal data you hold about me.",
                   "I would like to exercise my right to access and receive a copy of the personal data your company holds about me."],
         "details": ["I used your app through my former employer, {company}.",
                     "Please include where the data came from and who it was shared with."],
         "ask": ["Please confirm receipt and the expected timeline.", "Let me know if you need anything to verify my identity."]},
        {"id": "privacy-deletion", "priority": "P3", "urgency": ["medium", "low"], "intro": False,
         "why": "an erasure request is privacy; no deadline at risk, so P3",
         "subjects": ["Please delete my data", "Account and data deletion", "Erasure request"],
         "issue": ["I closed my account last month. Please delete my data, including any backups and marketing lists.",
                   "I ask you to erase all personal data about me under Article 17 GDPR."],
         "details": ["My account was under the {company} workspace.", "Please confirm when the deletion is complete."],
         "ask": ["Thank you.", "Please confirm in writing."]},
        {"id": "privacy-ccpa-optout", "priority": "P3", "urgency": ["low", "medium"], "intro": False,
         "why": "a CCPA opt-out is a rights request, so privacy P3",
         "subjects": ["CCPA opt-out request", "Do not sell or share my personal information", "California privacy request"],
         "issue": ["I am a California resident and, under the CCPA, I opt out of the sale or sharing of my personal information.",
                   "Please treat this as a CCPA request to stop selling or sharing my personal information."],
         "details": ["I am a user in the {company} workspace.", "This also covers any advertising partners."],
         "ask": ["Please confirm once this is done.", "Let me know if you need anything else from me."]},
        {"id": "privacy-dpa", "priority": "P3", "urgency": ["medium"],
         "why": "a DPA question is privacy; renewal is weeks away, so P3",
         "subjects": ["DPA and sub-processor list", "Data processing agreement request", "Need a signed DPA before renewal"],
         "issue": ["Our legal team needs a signed data processing agreement and your current list of sub-processors before we renew.",
                   "Before our renewal, we need your DPA and details on where our data is stored and which sub-processors you use."],
         "details": ["Our renewal is in three weeks.", "We are an EU company, so the transfer terms matter to us."],
         "ask": ["Who should we talk to?", "Please send the documents or a link."]},
        {"id": "privacy-rectification", "priority": "P3", "urgency": ["low"], "intro": False,
         "why": "a rectification request is privacy P3",
         "subjects": ["Correct my personal data", "Wrong name in your records", "Rectification request"],
         "issue": ["Your records still show my old surname. Under GDPR I ask you to correct it in all your systems.",
                   "Please correct my personal data under GDPR: my name changed, and invoices and emails still use the old one."],
         "details": ["I already changed it in my profile, but it did not reach the other systems.", "My account is part of the {company} workspace."],
         "ask": ["Thank you.", "Please confirm when it is done."]},
        {"id": "privacy-employee-dsar", "priority": "P2", "urgency": ["high"],
         "why": "a rights request with the legal deadline at risk is P2",
         "subjects": ["Urgent: data subject request from a former employee", "DSAR deadline tomorrow", "Need an export for a data subject request"],
         "issue": ["A former employee filed a data subject request with us, and we need to export everything your platform holds about them. Our deadline is tomorrow.",
                   "We have a data subject request from an ex-employee that is due tomorrow, and we cannot find how to export their activity and messages."],
         "details": ["We are the controller and you are our processor.", "We already searched the help center."],
         "ask": ["Please tell us how to get the export today.", "Can someone help us with this today?"]},
        {"id": "privacy-erasure-admin", "priority": "P3", "urgency": ["medium"],
         "why": "an erasure request is privacy even when the admin asks how to do it; P3",
         "subjects": ["User asked us to erase their data", "Erasure for a workspace user", "Fully removing a user's personal data"],
         "issue": ["A user in our workspace asked us to erase their personal data under GDPR. Deactivating them seems to keep their name and messages.",
                   "As the workspace admin, I received an erasure request under GDPR from one of our users and need to remove their personal data completely."],
         "details": ["We want to answer them within the month.", "We could not find a delete option for user data in the admin area."],
         "ask": ["How do we do this correctly?", "Can you do it for us or tell us the steps?"]},
    ],
    "other": [
        {"id": "other-sales-pitch", "priority": "P4", "urgency": ["low"], "intro": False,
         "why": "a sales pitch is other P4",
         "subjects": ["Grow your organic traffic by 300%", "Quick question about your marketing", "Partnership idea"],
         "issue": ["I'm {first} from {company}. We help software companies grow organic traffic with link building and content.",
                   "I'm reaching out from {company}; we run outbound campaigns for software companies like yours."],
         "details": ["We have worked with more than 200 brands.", "I would love 15 minutes of your time next week.",
                     "Our clients usually see results within the first three months."],
         "ask": ["Would you be open to a quick call?", "Who is the right person to talk to?"]},
        {"id": "other-thank-you", "priority": "P4", "urgency": ["low"],
         "why": "a thank-you note is other P4",
         "subjects": ["Thank you!", "Thanks for the help", "Great support"],
         "issue": ["Just wanted to say thanks to your support team for the help with our setup last week.",
                   "Thank you for the quick answer yesterday; everything works now."],
         "details": ["Really appreciated.", "Our team is very happy with the app.",
                     "The person who answered explained everything clearly and patiently."],
         "ask": ["Have a great week.", "Keep it up!"]},
        {"id": "other-wrong-recipient", "priority": "P4", "urgency": ["low"], "intro": False,
         "why": "a message sent to the wrong recipient is other P4",
         "subjects": ["Re: Q3 budget figures", "Meeting notes", "Fwd: lunch order"],
         "issue": ["I think I sent my last email to the wrong address. It was meant for our accounting firm.",
                   "Sorry, my previous message was meant for a colleague, not for you."],
         "details": ["Please disregard it.", "You can throw it away.",
                     "Our accounting firm has a very similar address, so the autocomplete picked yours."],
         "ask": ["Apologies for the noise.", "Sorry for the trouble."]},
        {"id": "other-job-application", "priority": "P4", "urgency": ["low"], "intro": False,
         "attachment": ("cv.pdf", "application/pdf"),
         "why": "a job application is other P4",
         "subjects": ["Application: Support Engineer", "Job application", "Open role in customer support"],
         "issue": ["I'm applying for the Support Engineer role I saw on your careers page.",
                   "I would like to apply for a position on your support team."],
         "details": ["I have four years of experience in SaaS support.", "My CV is attached.",
                     "I enjoy solving technical problems and explaining them in plain language."],
         "ask": ["I look forward to hearing from you.", "Thank you for considering me."]},
        {"id": "other-guest-post", "priority": "P4", "urgency": ["low"], "intro": False,
         "why": "a link-building pitch is other P4",
         "subjects": ["Guest post opportunity", "Link exchange proposal", "Content collaboration"],
         "issue": ["I'm {first}, editor at {company}. We would like to publish a guest article on your blog in exchange for a link.",
                   "We are offering free, high-quality articles for your blog in return for one link back to {company}."],
         "details": ["Our writers cover productivity and remote work.", "We can deliver the first article within a week.",
                     "All articles are original and written by people with industry experience."],
         "ask": ["Let me know if you are interested.", "Shall I send some topic ideas?"]},
        {"id": "other-webinar-invite", "priority": "P4", "urgency": ["low"], "intro": False,
         "why": "an event invitation is other P4",
         "subjects": ["Invitation to speak at our webinar", "Speaker invitation", "Join our panel next month"],
         "issue": ["We are hosting a webinar on customer operations next month and would love someone from your team on the panel.",
                   "I'm {first} from {company}, and I would like to invite your team to speak at our online event."],
         "details": ["The session is 45 minutes and fully online.", "Past speakers came from about 30 software companies.",
                     "We expect a few hundred people from operations and support teams to attend."],
         "ask": ["Would anyone be available?", "Who could I talk to about this?"]},
        {"id": "other-survey-reply", "priority": "P4", "urgency": ["low"],
         "why": "a survey reply with praise is other P4",
         "subjects": ["Re: How did we do?", "Survey reply", "Re: Your feedback matters"],
         "issue": ["I gave you five stars in the survey, but wanted to add a note: the onboarding call was excellent.",
                   "Replying to your survey: everything is going well, and the team likes the app."],
         "details": ["Special thanks to the person who ran our training.", "No complaints from our side.",
                     "We will recommend you to the other teams in our company."],
         "ask": ["Keep up the good work.", "Have a nice day."]},
    ],
}

# Duplicate traps: the same subject as an earlier ticket, a different issue (HARNESS_SPEC §1.1).
TRAPS = {
    "bug": {"priority": "P3", "urgency": "medium",
            "body": "Hi,\n\nI am reusing my earlier subject line, but this is a different problem: the date columns in "
                    "our CSV exports come out in US format, although our workspace is set to day/month/year. "
                    "Could you check it this week?\n\nThanks,\n{first}",
            "why": "a new display defect with a workaround (bug P3); this week = medium"},
    "billing": {"priority": "P4", "urgency": "low",
                "body": "Hello,\n\nSame subject as before, but a new question: our finance team would like the purchase "
                        "order number PO-{po} printed on future invoices. Is that possible? No rush.\n\n{full}",
                "why": "a general billing question with no impact (billing P4 low)"},
}

# PII bucket: category, base scenario, planted types (HARNESS_SPEC §1.1; values are published test/doc values).
PII_PLAN = (
    ("billing", "billing-double-charge", ("card", "phone")),
    ("access", "access-locked-admin", ("phone", "ipv4")),
    ("bug", "bug-upload-large", ("url", "ipv4")),
    ("privacy", "privacy-dsar-access", ("ssn", "email")),
    ("billing", "billing-downgrade-credit", ("iban", "email")),
    ("outage", "outage-all-500", ("ipv4", "phone")),
    ("access", "access-invite-expired", ("email", "phone")),
    ("howto", "howto-bulk-import", ("url", "email")),
    ("feature", "feature-outlook-sync", ("phone",)),
    ("bug", "bug-export-csv", ("url", "ipv4")),
    ("other", "other-sales-pitch", ("phone", "email")),
    ("billing", "billing-card-declined", ("card", "ssn", "iban")),
)
PII_VALUES = {
    "card": ("4111 1111 1111 1111", "5555-5555-5555-4444"),        # published test card numbers
    "ssn": ("987-65-4320", "987-65-4325"),                          # 987-65-432x: reserved, never issued
    "iban": ("DE89 3704 0044 0532 0130 00", "GB82 WEST 1234 5698 7654 32"),  # ISO 13616 documentation examples
    "phone": ("+1 415-555-0142", "(212) 555-0187", "+1 646 555 0123", "617-555-0199", "+1 (303) 555-0110",
              "312.555.0156"),
    "email": ("maria.lopez@ottervale.example.com", "j.berg@amberlow.example.org", "finance@quillmoor.example.org",
              "kai.nakamura@tidewell.example.com", "r.santos@velloran.example.net"),
    "ipv4": ("192.0.2.15", "198.51.100.23", "203.0.113.42", "203.0.113.7"),   # RFC 5737 documentation ranges
    "url": ("https://share.example.com/rec/8f3a2c?token=q7Rk2mZx91", "https://files.example.net/d/4471?sig=a81f0c&exp=1790000000",
            "https://drive.example.org/view?id=5521&key=Zp4Lk8"),
}
PII_SENTENCES = {
    "card": "For reference, the payment was made with card {v}.",
    "ssn": "For verification, my SSN is {v}.",
    "ssn_billing": "Our W-9 lists the SSN {v}, as I am a sole proprietor.",
    "iban": "If a refund is easier by bank transfer, our IBAN is {v}.",
    "phone": "You can reach me on {v} if a call is quicker.",
    "email": "Please copy my colleague at {v} on your reply.",
    "ipv4": "Our office egress IP is {v}, in case that helps with the logs.",
    "url": "Here is a screen recording of the problem: {v}",
}

FEATURE_ESSAY = (
    "Saved report views: let us save a filtered report with its columns and sort order, and share it with the team.",
    "Scheduled exports: send a saved view as a file to a list of people every week, on a day we choose.",
    "Cross-workspace reports: we run three workspaces and today we merge their numbers by hand every month.",
    "Custom date ranges: the fixed ranges (7, 30 and 90 days) do not match our fiscal quarters, which start in February.",
    "Goal lines on charts: a target line on the weekly chart would make the dashboard much easier to read in meetings.",
    "Drill-down: clicking a bar in a chart should open the list of records behind that number.",
    "Annotations: we would like to add a short note to a day on a chart, for example 'pricing change' or 'campaign start'.",
    "Report permissions: some reports should be visible to managers only, while others can be shared with the whole team.",
    "Comparisons: show this period next to the same period last year, with the difference in percent.",
    "Embeds: a read-only link to a single chart that we can place on our internal wiki page.",
    "Better CSV: keep number formats and add the report name and date range to the top of every export.",
    "Templates: a few ready-made report templates for common questions would help new team members start faster.",
)

# ---------------------------------------------------------------- helpers
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _fill(text, slots):
    return _PLACEHOLDER.sub(lambda m: slots[m.group(1)], text)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:00Z")


def _mail_date(dt):
    return "{}, {} {} {} at {:02d}:{:02d}".format(DAY_NAMES[dt.weekday()], dt.day, MONTH_NAMES[dt.month - 1], dt.year,
                                                  dt.hour, dt.minute)


def _writer(rng):
    first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
    company, slug, tld, region = rng.choice(COMPANIES)
    city1, city2 = rng.sample(CITIES[region], 2)
    cur = "$" if region == "US" else "€"
    seats = rng.randint(6, 40)
    return {
        "first": first, "last": last, "full": "{} {}".format(first, last), "company": company, "slug": slug,
        "tld": tld, "role": rng.choice(ROLES), "email": "{}.{}@{}.example.{}".format(first, last, slug, tld).lower(),
        "city1": city1, "city2": city2, "agent": AGENT,
        "plan": rng.choice(("Starter", "Team", "Business", "Scale")), "plan_low": rng.choice(("Starter", "Team")),
        "amount": "{}{:,.2f}".format(cur, rng.choice((49, 99, 149, 249, 490, 990, 1490, 2490))),
        "inv": "INV-2026-{:04d}".format(rng.randint(1000, 9999)), "month": rng.choice(("August", "September")),
        "weekday": rng.choice(("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")),
        "seats": str(seats), "seats_hi": str(seats + rng.randint(3, 12)),
        "time": "{:02d}:{:02d} UTC".format(rng.randint(6, 17), rng.choice((5, 10, 20, 35, 40, 50))),
        "n": rng.choice(("2,400", "3,100", "4,800", "12,000")), "po": str(rng.randint(40000, 49999)),
    }


def _scenario(category, scenario_id):
    for sc in SCENARIOS[category]:
        if sc["id"] == scenario_id:
            return sc
    raise KeyError(scenario_id)


def _compose(rng, sc, slots, urgency, extra=(), full_sign=False):
    """Render subject and body for one scenario. Labels are already fixed; the text follows them."""
    tones = ("neutral", "friendly", "formal") + (("frustrated",) if sc["priority"] in ("P1", "P2") else ())
    tone = rng.choice(tones)
    subject = _fill(rng.choice(sc["subjects"]), slots)
    first = []
    if sc.get("intro", True) and rng.random() < 0.7:
        first.append(_fill(rng.choice(INTROS), slots))
    first.append(_fill(rng.choice(sc["issue"]), slots))
    details = rng.sample(sc["details"], len(sc["details"]))
    n_details = rng.choice((1, 2))
    second = [_fill(d, slots) for d in details[:n_details]] + list(extra)
    if tone == "frustrated":
        second.append(rng.choice(FRUSTRATED))
    third = []
    if sc["category"] != "other" and (urgency != "low" or rng.random() < 0.5):
        third.append(rng.choice(URGENCY_PHRASES[urgency]))
    third.append(_fill(rng.choice(sc["ask"]), slots))
    style = "full" if full_sign else rng.choice(("first", "first", "full", "full_role"))
    signature = {"first": "{first}", "full": "{full}", "full_role": "{full}\n{role}, {company}"}[style]
    greeting, closing = rng.choice(GREETINGS[tone]), rng.choice(CLOSINGS[tone]) + "\n" + _fill(signature, slots)

    def body():
        return "\n\n".join((greeting, " ".join(first), " ".join(second), " ".join(third), closing))

    while len(body().split()) < MIN_CLEAN_WORDS and n_details < len(details):  # HARNESS_SPEC §1.1: 40-250 words
        second.insert(n_details, _fill(details[n_details], slots))
        n_details += 1
    return subject, body()


def _ticket(rng, input_id, slots, subject, body, received, attachments=(), source=None, message_id=True):
    source = source or ("webhook" if rng.random() < 0.15 else "email")
    ticket = {"source": source}
    if message_id:
        ticket["source_message_id"] = ("<{}@mail.example.com>".format(input_id) if source == "email"
                                       else "form-{}".format(input_id))
    ticket.update({"from_name": slots["full"], "from_email": slots["email"], "subject": subject, "body_text": body,
                   "received_at": received, "attachments": [dict(a) for a in attachments]})
    return ticket


def _outcome(category):
    return "review" if category in ALWAYS_REVIEW else "auto_route"


def _gold(input_id, split, bucket, ticket, labels, outcome, label_notes, template, hard_case=None, review_reason=None,
          pii=(), injection=None, duplicate_of=None):
    if outcome == "review" and review_reason is None:
        review_reason = "policy_class"
    try:
        dkey = dedupe_key(ticket.get("source"), ticket.get("source_message_id"))
    except ValueError:
        dkey = None  # missing message id: intake rejects it (C-3); no shared key (OPEN_QUESTIONS Q-19)
    return {
        "input_id": input_id, "synthetic": True, "split": split, "label_bucket": bucket, "hard_case": hard_case,
        "ticket": ticket,
        "expected": {"category": labels[0], "priority": labels[1], "urgency": labels[2]},
        "expect_outcome": outcome, "must_review": outcome in ("review", "rejected"), "review_reason": review_reason,
        "dedupe_key": dkey,
        "content_sha256": content_sha256(ticket.get("from_email"), ticket.get("subject"), ticket.get("body_text")),
        "duplicate_of": duplicate_of, "pii": [dict(p) for p in pii], "injection": injection, "fault": None,
        "label_notes": label_notes,
        "generator": {"seed": SEED, "template": template, "version": VERSION},
    }


def _render_quoted(body, quoted, received, slots):
    out = [body]
    for j, q in enumerate(quoted):
        when = received - timedelta(days=q["days_before"], hours=j + 1, minutes=7 * (j + 1))
        name = "{} (Support)".format(AGENT) if q["from"] == "agent" else slots["full"]
        head = (">" * j + " " if j else "") + "On {}, {} wrote:".format(_mail_date(when), name)
        lines = textwrap.wrap(_fill(q["text"], slots), 76)
        out.append(head + "\n" + "\n".join(">" * (j + 1) + " " + line for line in lines))
    return "\n\n".join(out)


def _load_hand_authored():
    return json.loads(HARD_CASES.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- build
def build():
    """Return the 200 gold dicts in manifest order. Pure function of SEED and hard_cases.json."""
    hand = _load_hand_authored()
    t_rng = random.Random("{}:time".format(SEED))
    times = [_iso(BASE_TIME + timedelta(minutes=197 * i + t_rng.randint(0, 120))) for i in range(200)]
    golds = []

    def next_id():
        return "t4-{:03d}".format(len(golds) + 1)

    # clean: 13 per category, round-robin; split alternates inside each category (7/6 or 6/7)
    rng = random.Random("{}:clean".format(SEED))
    for k in range(13):
        for ci, cat in enumerate(CATEGORIES):
            input_id = next_id()
            scs = SCENARIOS[cat]
            sc = dict(scs[(k + ci) % len(scs)], category=cat)
            urgency = rng.choice(sc["urgency"])
            split = "dev" if (k + ci) % 2 == 0 else "test"
            slots = _writer(rng)
            subject, body = _compose(rng, sc, slots, urgency)
            attachments = []
            if sc.get("attachment"):
                attachments.append({"name": sc["attachment"][0], "type": sc["attachment"][1],
                                    "bytes": rng.randint(40000, 400000)})
            elif cat in ("bug", "outage") and rng.random() < 0.3:
                attachments.append({"name": "screenshot.png", "type": "image/png", "bytes": rng.randint(40000, 400000)})
            ticket = _ticket(rng, input_id, slots, subject, body, times[len(golds)], attachments)
            notes = "clean {} ({}): {}; urgency {}: {}.".format(cat, sc["id"], sc["why"], urgency, URGENCY_WHY[urgency])
            golds.append(_gold(input_id, split, "clean", ticket, (cat, sc["priority"], urgency), _outcome(cat), notes,
                               sc["id"]))

    # hard: hand-authored, 6 per category, round-robin; split alternates (3/3), offset by category so each kind
    # lands in both splits
    rng = random.Random("{}:hard".format(SEED))
    by_cat = {c: [h for h in hand["hard"] if h["category"] == c] for c in CATEGORIES}
    for k in range(6):
        for ci, cat in enumerate(CATEGORIES):
            h = by_cat[cat][k]
            input_id = next_id()
            slots = _writer(rng)
            received = times[len(golds)]
            body = _fill(h["body"], slots)
            if h.get("quoted"):
                when = datetime.strptime(received, "%Y-%m-%dT%H:%M:00Z").replace(tzinfo=timezone.utc)
                body = _render_quoted(body, h["quoted"], when, slots)
            ticket = _ticket(rng, input_id, slots, _fill(h["subject"], slots), body, received,
                             h.get("attachments", ()), source="email")
            golds.append(_gold(input_id, "dev" if (k + ci) % 2 == 0 else "test", "hard", ticket,
                               (cat, h["priority"], h["urgency"]), _outcome(cat), h["label_notes"], h["id"],
                               hard_case=h["hard_case"]))

    # injection: hand-authored, split fixed in the file (4 direct + 4 indirect per split)
    rng = random.Random("{}:injection".format(SEED))
    for e in hand["injection"]:
        input_id = next_id()
        slots = _writer(rng)
        if e.get("b64_payload"):
            slots = dict(slots, b64=base64.b64encode(e["b64_payload"].encode("utf-8")).decode("ascii"))
        ticket = _ticket(rng, input_id, slots, _fill(e["subject"], slots), _fill(e["body"], slots),
                         times[len(golds)], e.get("attachments", ()), source="email")
        golds.append(_gold(input_id, e["split"], "injection", ticket, (e["category"], e["priority"], e["urgency"]),
                           "review", e["label_notes"], e["id"], review_reason="injection", pii=e.get("pii", ()),
                           injection=e["injection"]))

    # pii: clean-style tickets with planted values; sender name signed in full
    rng = random.Random("{}:pii".format(SEED))
    used = {t: 0 for t in PII_VALUES}
    for i, (cat, sc_id, types) in enumerate(PII_PLAN):
        input_id = next_id()
        sc = dict(_scenario(cat, sc_id), category=cat)
        urgency = rng.choice(sc["urgency"])
        slots = _writer(rng)
        pii, extra = [], []
        for t in types:
            value = PII_VALUES[t][used[t]]
            used[t] += 1
            key = "ssn_billing" if (t == "ssn" and cat == "billing") else t
            extra.append(PII_SENTENCES[key].format(v=value))
            pii.append({"type": t, "value": value})
        pii.append({"type": "name", "value": slots["full"]})
        subject, body = _compose(rng, sc, slots, urgency, extra=extra, full_sign=True)
        ticket = _ticket(rng, input_id, slots, subject, body, times[len(golds)])
        notes = "pii {} ({}): {}; urgency {}: {}; planted: {}.".format(cat, sc_id, sc["why"], urgency,
                                                                         URGENCY_WHY[urgency], ", ".join(types + ("name",)))
        golds.append(_gold(input_id, "dev" if i % 2 == 0 else "test", "pii", ticket, (cat, sc["priority"], urgency),
                           _outcome(cat), notes, sc_id, pii=pii))

    # duplicate: per split 3 resends, 2 content duplicates, 1 trap; originals are earlier clean tickets
    rng = random.Random("{}:duplicate".format(SEED))
    originals = set()
    resends = []
    for split, trap_cat in (("dev", "bug"), ("test", "billing")):
        pool = [g for g in golds if g["label_bucket"] == "clean" and g["split"] == split
                and g["expected"]["category"] not in ALWAYS_REVIEW]
        picked = sorted(rng.sample([g for g in pool if g["expected"]["category"] != trap_cat], 5),
                        key=lambda g: g["input_id"])
        trap_of = rng.choice([g for g in pool if g["expected"]["category"] == trap_cat])
        originals.update(g["input_id"] for g in picked + [trap_of])
        for j, orig in enumerate(picked):
            input_id = next_id()
            exp = orig["expected"]
            labels = (exp["category"], exp["priority"], exp["urgency"])
            if j < 3:
                ticket = json.loads(json.dumps(orig["ticket"]))
                notes = "duplicate: resend of {} with the same source_message_id (webhook retry / re-delivery).".format(
                    orig["input_id"])
                template = "duplicate-resend:{}".format(orig["input_id"])
            else:
                ticket = json.loads(json.dumps(orig["ticket"]))
                ticket["source_message_id"] = ("<{}@mail.example.com>".format(input_id) if ticket["source"] == "email"
                                               else "form-{}".format(input_id))
                ticket["received_at"] = times[len(golds)]
                if j == 4:  # same text, different case and line endings: content_sha256 must still match
                    ticket["subject"] = ticket["subject"].upper()
                    ticket["body_text"] = ticket["body_text"].replace("\n", "\r\n")
                notes = "duplicate: same sender, subject and body as {} with a new message id.".format(orig["input_id"])
                template = "duplicate-content:{}".format(orig["input_id"])
            gold = _gold(input_id, split, "duplicate", ticket, labels, "duplicate_skip", notes, template,
                         pii=orig["pii"], duplicate_of=orig["input_id"])
            if j < 3:
                resends.append(gold)
            golds.append(gold)
        input_id = next_id()
        trap = TRAPS[trap_cat]
        slots = _writer(rng)
        slots.update({k: trap_of["ticket"][v] for k, v in (("full", "from_name"), ("email", "from_email"))})
        slots["first"] = slots["full"].split(" ")[0]
        ticket = _ticket(rng, input_id, slots, trap_of["ticket"]["subject"], _fill(trap["body"], slots),
                         times[len(golds)], source=trap_of["ticket"]["source"])
        notes = "duplicate trap: same sender and subject as {}, different issue, so a new ticket: {}.".format(
            trap_of["input_id"], trap["why"])
        golds.append(_gold(input_id, split, "duplicate", ticket, (trap_cat, trap["priority"], trap["urgency"]),
                           _outcome(trap_cat), notes, "duplicate-trap:{}".format(trap_of["input_id"])))

    # malformed: one per category; six are rejected at intake (C-2, C-3), two go through as labelled
    rng = random.Random("{}:malformed".format(SEED))
    for i, build_one in enumerate(_MALFORMED):
        input_id = next_id()
        slots = _writer(rng)
        golds.append(build_one(rng, input_id, slots, times[len(golds)], "dev" if i % 2 == 0 else "test"))

    # faults (test split, pass A only): on auto-routed clean tickets that are not duplicate originals
    rng = random.Random("{}:fault".format(SEED))
    pool = [g for g in golds if g["split"] == "test" and g["label_bucket"] == "clean"
            and g["expect_outcome"] == "auto_route" and g["input_id"] not in originals]
    modes = [m for m, n in FAULTS_TEST for _ in range(n)]
    for gold, (target, mode) in zip(sorted(rng.sample(pool, len(modes)), key=lambda g: g["input_id"]), modes):
        gold["fault"] = {"target": target, "mode": mode, "pass": "A"}
    lag = next(g for g in resends if g["split"] == "test")
    lag["fault"] = {"target": "jira", "mode": "search_lag", "pass": "A"}

    _validate(golds)
    return golds


# ---------------------------------------------------------------- malformed builders
def _malformed_gold(input_id, split, ticket, labels, code, notes):
    outcome = "rejected" if code else _outcome(labels[0])
    return _gold(input_id, split, "malformed", ticket, labels, outcome, notes,
                 "malformed-{}".format(code or "as-label"), review_reason="malformed:{}".format(code) if code else None)


def _m_body_too_long(rng, input_id, slots, received, split):
    rows = ["date,invoice,item,qty,amount"]
    items = ("Team plan seat", "Business plan seat", "Storage add-on", "SSO add-on")
    i = 0
    while sum(len(r) + 1 for r in rows) <= MAX_BODY_CHARS + 400:
        rows.append("2026-08-{:02d},INV-2026-{:04d},{},1,{:.2f}".format(i % 28 + 1, 4000 + i, items[i % 4],
                                                                       (49, 99, 15, 30)[i % 4]))
        i += 1
    body = ("Hi,\n\nOur billing totals do not match our bank statement. I pasted our full billing export below. "
            "Can you check it line by line this week?\n\n" + "\n".join(rows) + "\n\nThanks,\n" + slots["first"])
    ticket = _ticket(rng, input_id, slots, "Billing totals do not match", body, received)
    notes = "malformed body_too_long: body is {:,} chars (> {:,}), rejected before the model (C-2); labels describe " \
            "the visible request (billing P3 medium).".format(len(body), MAX_BODY_CHARS)
    return _malformed_gold(input_id, split, ticket, ("billing", "P3", "medium"), "body_too_long", notes)


def _m_empty(rng, input_id, slots, received, split):
    ticket = _ticket(rng, input_id, slots, "", "", received)
    notes = "malformed empty_content: subject and body are empty, rejected at intake (C-3); nothing to route, so other P4 low."
    return _malformed_gold(input_id, split, ticket, ("other", "P4", "low"), "empty_content", notes)


def _m_missing_id(rng, input_id, slots, received, split):
    sc = dict(_scenario("access", "access-reset-email"), category="access")
    subject, body = _compose(rng, sc, slots, "medium")
    ticket = _ticket(rng, input_id, slots, subject, body, received, source="email", message_id=False)
    notes = "malformed missing_message_id: no source_message_id, rejected at intake (C-3), dedupe_key null; labels " \
            "describe the visible request (access P3 medium)."
    return _malformed_gold(input_id, split, ticket, ("access", "P3", "medium"), "missing_message_id", notes)


def _m_attachments(rng, input_id, slots, received, split):
    sc = dict(_scenario("bug", "bug-chart-duplicate"), category="bug")
    subject, body = _compose(rng, sc, slots, "medium", extra=("I attached twelve screenshots, one per browser and zoom level.",))
    files = [{"name": "screenshot-{:02d}.png".format(n), "type": "image/png", "bytes": rng.randint(40000, 400000)}
             for n in range(1, MAX_ATTACHMENTS + 3)]
    ticket = _ticket(rng, input_id, slots, subject, body, received, files)
    notes = "malformed too_many_attachments: {} attachments (> {}), rejected at intake (C-2); labels describe the " \
            "visible request (bug P3 medium).".format(len(files), MAX_ATTACHMENTS)
    return _malformed_gold(input_id, split, ticket, ("bug", "P3", "medium"), "too_many_attachments", notes)


def _m_exe(rng, input_id, slots, received, split):
    body = ("Hi,\n\nHow do I install the desktop sync client? I attached the installer I downloaded; is it the "
            "right one for Windows?\n\nThanks,\n" + slots["first"])
    files = [{"name": "SyncSetup-2.4.exe", "type": "application/x-msdownload", "bytes": 48203776}]
    ticket = _ticket(rng, input_id, slots, "Desktop client installer", body, received, files)
    notes = "malformed attachment_type: an .exe attachment, outside the allowed types, rejected at intake (C-2); " \
            "labels describe the visible request (howto P4 low)."
    return _malformed_gold(input_id, split, ticket, ("howto", "P4", "low"), "attachment_type", notes)


def _m_control_chars(rng, input_id, slots, received, split):
    body = ("Hi,\n\nThe API returns 503 for every request across all our workspaces. Output from our health check:\n\n"
            "\x1b[31mERROR\x1b[0m GET /v2/projects -> 503 Service Unavailable\x00\n"
            "\x1b[31mERROR\x1b[0m GET /v2/tasks -> 503 Service Unavailable\x07\n"
            "\x1b[31mERROR\x1b[0m POST /v2/events -> 503 Service Unavailable\x08\x7f\n\n"
            "This has been going on since {}. Please fix it now.\n\n{}".format(slots["time"], slots["first"]))
    ticket = _ticket(rng, input_id, slots, "API 503 on all workspaces", body, received)
    notes = "malformed control_characters: terminal escape and NUL/BEL/BS/DEL characters in the body; intake must not " \
            "crash, the ticket goes through as labelled (outage P1 high)."
    return _malformed_gold(input_id, split, ticket, ("outage", "P1", "high"), None, notes)


def _m_long_subject(rng, input_id, slots, received, split):
    sc = dict(_scenario("privacy", "privacy-deletion"), category="privacy")
    _, body = _compose(rng, sc, slots, "medium")
    phrase = "Request to delete my account and personal data - please read - "
    subject = (phrase * (1000 // len(phrase) + 1))[:1000].rstrip()
    subject = subject + "!" * (1000 - len(subject))
    ticket = _ticket(rng, input_id, slots, subject, body, received)
    notes = "malformed subject_too_long: subject is {:,} chars (> {}), rejected at intake (C-2, SEC-10); labels " \
            "describe the visible request (privacy P3 medium).".format(len(subject), MAX_SUBJECT_CHARS)
    return _malformed_gold(input_id, split, ticket, ("privacy", "P3", "medium"), "subject_too_long", notes)


def _m_model_cap(rng, input_id, slots, received, split):
    head = ("Hi team,\n\nWe have used your reporting module for a year, and our managers asked me to collect "
            "everything we miss in one place. Here is the full list, in order of importance:\n\n")
    foot = "\n\nThanks for reading all of this.\n" + slots["full"]
    items, n = [], 0
    while len(head + "\n".join(items) + foot) < MAX_MODEL_CHARS - 150:
        items.append("{}. {}".format(n + 1, FEATURE_ESSAY[n % len(FEATURE_ESSAY)]))
        n += 1
    while len(head + "\n".join(items) + foot) > MAX_MODEL_CHARS:
        items.pop()
    filler = "\n\nNone of this is urgent, but together these changes would make the reports far more useful"
    body = head + "\n".join(items) + filler
    body = (body + "." * (MAX_MODEL_CHARS - len(body + foot)))[:MAX_MODEL_CHARS - len(foot)] + foot
    ticket = _ticket(rng, input_id, slots, "Reporting wish list", body, received)
    notes = "malformed body_at_model_cap: body is exactly {:,} chars (= max_model_chars), not truncated; goes " \
            "through as labelled (feature P4 low).".format(len(body))
    return _malformed_gold(input_id, split, ticket, ("feature", "P4", "low"), None, notes)


_MALFORMED = (_m_body_too_long, _m_empty, _m_missing_id, _m_attachments, _m_exe, _m_control_chars, _m_long_subject,
              _m_model_cap)


# ---------------------------------------------------------------- validation and output
def _validate(golds):
    """Fail the build, not the morning, if the set breaks HARNESS_SPEC §1.1."""
    problems = []
    if [g["input_id"] for g in golds] != ["t4-{:03d}".format(i) for i in range(1, 201)]:
        problems.append("ids must be t4-001..t4-200")
    for bucket, n in BUCKETS:
        got = sum(1 for g in golds if g["label_bucket"] == bucket)
        if got != n:
            problems.append("bucket {} has {} (want {})".format(bucket, got, n))
    for split in ("dev", "test"):
        got = sum(1 for g in golds if g["split"] == split)
        if got != 100:
            problems.append("split {} has {}".format(split, got))
    for g in golds:
        e = g["expected"]
        if e["category"] not in CATEGORIES or e["priority"] not in PRIORITIES or e["urgency"] not in URGENCIES:
            problems.append("{}: label outside enum".format(g["input_id"]))
        if g["label_bucket"] == "clean":
            words = len(g["ticket"]["body_text"].split())
            if not MIN_CLEAN_WORDS <= words <= MAX_CLEAN_WORDS:
                problems.append("{}: clean body has {} words".format(g["input_id"], words))
    if problems:
        raise ValueError("golden set invalid: " + "; ".join(problems))


def _gold_text(gold):
    return json.dumps(gold, indent=2, ensure_ascii=False) + "\n"


def _manifest_text(golds):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(MANIFEST_HEADER)
    for g in golds:
        e = g["expected"]
        w.writerow([g["input_id"], g["split"], g["label_bucket"], e["category"], e["priority"], e["urgency"],
                    g["expect_outcome"], "{}/{}.json".format(GOLD_DIR, g["input_id"])])
    return buf.getvalue()


def render(golds):
    """{relative path: file text} for every generated file."""
    files = {"{}/{}.json".format(GOLD_DIR, g["input_id"]): _gold_text(g) for g in golds}
    files[MANIFEST] = _manifest_text(golds)
    return files


def stats_block(golds):
    """Markdown for evals/README.md § Label stats. Counts only; generated, never typed."""
    def count(**kw):
        return sum(1 for g in golds if all(_field(g, k) == v for k, v in kw.items()))

    lines = [STATS_START, "", "Cells are dev / test counts.", "",
             "| bucket | " + " | ".join(CATEGORIES) + " | total |", "|---" * (len(CATEGORIES) + 2) + "|"]
    for bucket, _ in BUCKETS:
        cells = ["{} / {}".format(count(label_bucket=bucket, category=c, split="dev"),
                                  count(label_bucket=bucket, category=c, split="test")) for c in CATEGORIES]
        lines.append("| {} | {} | {} / {} |".format(bucket, " | ".join(cells), count(label_bucket=bucket, split="dev"),
                                                     count(label_bucket=bucket, split="test")))
    cells = ["{} / {}".format(count(category=c, split="dev"), count(category=c, split="test")) for c in CATEGORIES]
    lines.append("| all | {} | {} / {} |".format(" | ".join(cells), count(split="dev"), count(split="test")))
    lines += ["", "| label | value | dev | test | total |", "|---|---|---|---|---|"]
    for field, values in (("priority", PRIORITIES), ("urgency", URGENCIES), ("expect_outcome", OUTCOMES),
                          ("hard_case", HARD_KINDS)):
        for v in values:
            d, t = count(**{field: v, "split": "dev"}), count(**{field: v, "split": "test"})
            lines.append("| {} | {} | {} | {} | {} |".format(field, v, d, t, d + t))
    faults = sorted({(g["fault"]["target"], g["fault"]["mode"]) for g in golds if g["fault"]})
    for target, mode in faults:
        n = sum(1 for g in golds if g["fault"] and (g["fault"]["target"], g["fault"]["mode"]) == (target, mode))
        lines.append("| fault (test, pass A) | {}:{} | 0 | {} | {} |".format(target, mode, n, n))
    lines += ["", STATS_END]
    return "\n".join(lines)


def _field(gold, key):
    if key in ("category", "priority", "urgency"):
        return gold["expected"][key]
    return gold[key]


def _readme_with_stats(text, block):
    start, end = text.find(STATS_START), text.find(STATS_END)
    if start < 0 or end < 0:
        raise ValueError("{} lacks the label-stats markers".format(README))
    return text[:start] + block + text[end + len(STATS_END):]


def write(root, golds=None):
    golds = golds if golds is not None else build()
    for rel, text in render(golds).items():
        path = Path(root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    readme = Path(root) / README
    if readme.exists():
        text = readme.read_text(encoding="utf-8")
        new = _readme_with_stats(text, stats_block(golds))
        if new != text:
            with readme.open("w", encoding="utf-8", newline="\n") as f:
                f.write(new)
    return golds


def check(root=ROOT):
    """Regenerate into a temp dir and compare byte for byte with the files under root. Returns an exit code."""
    golds = build()
    problems = []
    tmp = Path(tempfile.mkdtemp(prefix="t4-gold-"))
    try:
        write(tmp, golds)
        for rel in sorted(render(golds)):
            want, have = (tmp / rel).read_bytes(), Path(root) / rel
            if not have.exists():
                problems.append("missing {}".format(rel))
            elif have.read_bytes() != want:
                problems.append("differs {}".format(rel))
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    expected = {"{}.json".format(g["input_id"]) for g in golds}
    gold_dir = Path(root) / GOLD_DIR
    extra = sorted(p.name for p in gold_dir.glob("*.json") if p.name not in expected) if gold_dir.is_dir() else []
    problems += ["extra {}/{}".format(GOLD_DIR, name) for name in extra]
    readme = Path(root) / README
    if not readme.exists() or stats_block(golds) not in readme.read_text(encoding="utf-8"):
        problems.append("{} § Label stats is stale".format(README))
    for p in problems:
        print("FAIL: " + p)
    if problems:
        print("FAIL: golden set differs from the generator ({} problem(s)); run python3 -m src.fixtures.make_tickets"
              .format(len(problems)))
        return 1
    print("ok: golden set matches the generator (200 gold files, manifest, label stats)")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="regenerate into a temp dir and diff; write nothing")
    p.add_argument("--out", default=str(ROOT), help="root to write into (default: the repo)")
    args = p.parse_args(argv)
    if args.check:
        return check(Path(args.out))
    golds = write(Path(args.out))
    print("ok: wrote {} gold files, {} and label stats under {}".format(len(golds), MANIFEST, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
