import os
import json
import streamlit as st
import anthropic
from utils import rate_limit

st.set_page_config(
    page_title="IT Ops Bot — Demo",
    page_icon="🤖",
    layout="wide",
)

# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.markdown("## 🤖 IT Ops Bot")
st.sidebar.markdown(
    "Simulate the three Slack slash commands — `/itrequest`, `/accessrequest`, `/incident` — "
    "powered by Claude AI. No Slack, Jira, or Confluence setup required."
)
st.sidebar.markdown("---")
st.sidebar.markdown(
    "In production this runs inside Slack: slash commands open modals, Claude analyzes the "
    "input, and results post to team channels with Approve/Deny buttons or Jira ticket links."
)
st.sidebar.markdown("---")
st.sidebar.markdown("Built by [Oleg Strutsovski](https://linkedin.com/in/olegst)")


# ── API client ────────────────────────────────────────────────────────────────
def get_client():
    api_key = None
    for key in ["ANTHROPIC_API_KEY", "anthropic_api_key"]:
        try:
            api_key = st.secrets[key]
            break
        except Exception:
            pass
    if not api_key:
        try:
            api_key = st.secrets["anthropic"]["api_key"]
        except Exception:
            pass
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        st.error(
            "Anthropic API key not configured. In Streamlit Cloud secrets, paste:\n\n"
            "```\nANTHROPIC_API_KEY = \"sk-ant-...\"\n```"
        )
        st.stop()
    return anthropic.Anthropic(api_key=api_key)


# ── Claude prompts (same as the Slack bot's claude_ops.py) ────────────────────
_TRIAGE_SYSTEM = """You are an expert IT helpdesk triage specialist. Given an IT support request, return a JSON object:
{
  "category": str,
  "priority": str,
  "sla_hours": int,
  "owner": str,
  "suggested_action": str,
  "auto_resolvable": bool,
  "tags": [str]
}

category: "Access & Auth" | "Hardware" | "Software & Apps" | "Network & Connectivity" | "Onboarding/Offboarding" | "Security" | "Other"
priority: "P1 - Critical" | "P2 - High" | "P3 - Medium" | "P4 - Low"
sla_hours: 4 | 8 | 24 | 72
owner: "Identity & Access Team" | "IT Support (Tier 1)" | "IT Support (Tier 2)" | "Infrastructure Team" | "IT Manager" | "HR + IT Joint"
suggested_action: 2-3 sentences, specific next step
tags: 1-3 from ["password-reset","mfa","access-request","offboarding","onboarding","hardware-failure","software-license","vpn","sso","mdm","compliance","vendor-app","network"]

Priority:
- P1: complete blockage, exec/customer-facing, security risk, >5 users, data loss
- P2: significant impairment, time-sensitive, single user blocked on critical tool
- P3: partial impairment, workaround exists
- P4: non-urgent, low-impact

Return ONLY valid JSON. No markdown."""

_RISK_SYSTEM = """You are an IAM security analyst. Given an access request, return a JSON object:
{
  "risk_level": str,
  "risk_factors": [str],
  "recommendation": str,
  "rationale": str,
  "sox_sensitive": bool,
  "auto_approve": bool
}

risk_level: "Low" | "Medium" | "High"
recommendation: "Approve" | "Review" | "Deny"
rationale: 2 sentences
sox_sensitive: true for Salesforce, NetSuite, Workday, GitHub, AWS, Okta, financial systems
auto_approve: true ONLY if risk_level is "Low" AND access_level is read-only or user
risk_factors: specific concerns, empty list for Low risk

Risk logic:
- Admin/super-admin on sensitive system = High
- SOX-sensitive + elevated access = High
- Vague or insufficient justification = Medium
- Read-only + non-sensitive + clear justification = Low

Return ONLY valid JSON. No markdown."""

_INCIDENT_SYSTEM = """You are an incident commander. Given a production incident, return a JSON object:
{
  "summary": str,
  "immediate_actions": [str],
  "notify_teams": [str],
  "user_impact": str,
  "estimated_scope": str
}

summary: 1-2 sentence plain-English summary
immediate_actions: 3-5 specific, ordered actions to take right now
notify_teams: e.g. ["Engineering", "Customer Success", "IT"]
user_impact: who is affected and how
estimated_scope: scale, e.g. "~500 affected users" or "All production traffic"

Return ONLY valid JSON. No markdown."""


def _parse(raw: str) -> dict:
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def run_triage(subject: str, description: str, urgency: str, department: str) -> dict:
    msg = get_client().messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        system=_TRIAGE_SYSTEM,
        messages=[{"role": "user", "content": json.dumps({
            "subject": subject, "description": description,
            "urgency": urgency, "department": department,
        })}],
    )
    return _parse(msg.content[0].text.strip())


def run_risk(app_name: str, access_level: str, justification: str, manager: str) -> dict:
    msg = get_client().messages.create(
        model="claude-sonnet-4-5",
        max_tokens=512,
        system=_RISK_SYSTEM,
        messages=[{"role": "user", "content": json.dumps({
            "app_name": app_name, "access_level": access_level,
            "justification": justification, "manager_name": manager,
        })}],
    )
    return _parse(msg.content[0].text.strip())


def run_incident(title: str, systems: str, description: str, severity: str) -> dict:
    msg = get_client().messages.create(
        model="claude-sonnet-4-5",
        max_tokens=512,
        system=_INCIDENT_SYSTEM,
        messages=[{"role": "user", "content": json.dumps({
            "title": title, "systems_affected": systems,
            "description": description, "severity": severity,
        })}],
    )
    return _parse(msg.content[0].text.strip())


# ── Constants ─────────────────────────────────────────────────────────────────
_PRIORITY_ICON = {
    "P1 - Critical": "🔴",
    "P2 - High": "🟠",
    "P3 - Medium": "🟡",
    "P4 - Low": "🟢",
}
_URGENCY    = ["Low", "Medium", "High", "Critical"]
_DEPARTMENT = ["Engineering", "Sales", "Finance", "HR", "Legal", "Operations", "IT", "Executive"]
_ACCESS     = ["Read-only", "User", "Admin", "Super Admin"]
_SEVERITY   = ["SEV-1", "SEV-2", "SEV-3"]

_EX_IT = {
    "subject":     "Okta locked out — board presentation in 1 hour",
    "description": (
        "My Okta authenticator shows 'invalid code' for every login attempt. "
        "I have an all-hands presentation in 60 minutes and need access to "
        "Google Slides, Zoom, and Salesforce."
    ),
    "urgency":     "Critical",
    "department":  "Executive",
}
_EX_ACCESS = {
    "app_name":      "Salesforce",
    "access_level":  "Admin",
    "justification": (
        "Need to run quarterly financial close reports and reconcile "
        "opportunity data for the board deck."
    ),
    "manager": "Sarah Chen",
}
_EX_INCIDENT = {
    "title":       "API gateway returning 502 errors — all users affected",
    "severity":    "SEV-1",
    "systems":     "api-gateway, auth-service, postgres",
    "description": (
        "Starting at 14:32 UTC, our API gateway began returning 502 errors for all requests. "
        "Error rate jumped from <0.1% to 100% over 3 minutes. Auth service logs show timeout "
        "connecting to postgres. Database CPU at 100%, connections exhausted. "
        "~1,200 active users cannot access the platform."
    ),
}


# ── Session state ─────────────────────────────────────────────────────────────
for _k in ("it_result", "access_result", "incident_result"):
    if _k not in st.session_state:
        st.session_state[_k] = None


# ── Page header ───────────────────────────────────────────────────────────────
st.title("IT Ops Bot — Demo")
st.caption(
    "Simulate the three Slack slash commands powered by Claude AI. "
    "No Slack, Jira, or Confluence setup required."
)

ip = rate_limit.get_client_ip()
remaining = rate_limit.remaining(ip)

tab_it, tab_access, tab_incident = st.tabs([
    "🎫  /itrequest",
    "🔑  /accessrequest",
    "🚨  /incident",
])


# ═══════════════════════════════════════════════════════════════════════════════
# Tab 1 — /itrequest
# ═══════════════════════════════════════════════════════════════════════════════
with tab_it:
    left, right = st.columns([4, 6])

    with left:
        st.subheader("IT Request")
        if st.button("Pre-fill with example", key="it_btn_prefill"):
            st.session_state.it_subject = _EX_IT["subject"]
            st.session_state.it_desc    = _EX_IT["description"]
            st.session_state.it_urgency = _EX_IT["urgency"]
            st.session_state.it_dept    = _EX_IT["department"]

        subject = st.text_input(
            "Subject", key="it_subject",
            placeholder="One-line summary of the issue",
        )
        description = st.text_area(
            "Description", key="it_desc",
            height=140, max_chars=2000,
            placeholder="What's happening? What have you tried?",
        )
        urgency = st.selectbox("Urgency", _URGENCY, key="it_urgency")
        department = st.selectbox("Department", _DEPARTMENT, key="it_dept")

        if st.button("Submit Request", type="primary", use_container_width=True,
                     key="it_submit", disabled=remaining == 0):
            if not subject or not description:
                st.warning("Subject and description are required.")
            elif rate_limit.is_allowed(ip):
                rate_limit.record(ip)
                with st.spinner("Claude is triaging your request..."):
                    try:
                        st.session_state.it_result = run_triage(
                            subject, description, urgency, department
                        )
                    except Exception as e:
                        st.error(f"Error: {e}")

        if remaining == 0:
            st.error(f"Daily limit reached ({rate_limit.DAILY_LIMIT}/IP/day). Try again tomorrow.")
        else:
            st.caption(f"{remaining} of {rate_limit.DAILY_LIMIT} requests remaining today")

    with right:
        st.subheader("Triage Result")
        result = st.session_state.it_result
        if result:
            priority = result.get("priority", "")
            icon = _PRIORITY_ICON.get(priority, "⚪")
            sla = result.get("sla_hours", "—")

            st.markdown(f"### {icon} {priority}")

            c1, c2, c3 = st.columns(3)
            c1.metric("SLA", f"{sla}h")
            c2.metric("Category", result.get("category", ""))
            c3.metric("Owner", result.get("owner", ""))

            st.info(f"**Suggested Action**\n\n{result.get('suggested_action', '')}")

            tags = result.get("tags", [])
            if tags:
                st.markdown("**Tags:** " + "  ".join(f"`{t}`" for t in tags))

            auto = result.get("auto_resolvable", False)
            st.markdown(f"**Auto-resolvable:** {'✅ Yes' if auto else '❌ No'}")

            st.divider()
            st.download_button(
                "Download JSON",
                data=json.dumps(result, indent=2),
                file_name="triage_result.json",
                mime="application/json",
                key="it_download",
            )
        else:
            st.markdown("*Submit a request on the left to see the triage output here.*")


# ═══════════════════════════════════════════════════════════════════════════════
# Tab 2 — /accessrequest
# ═══════════════════════════════════════════════════════════════════════════════
with tab_access:
    left, right = st.columns([4, 6])

    with left:
        st.subheader("Access Request")
        if st.button("Pre-fill with example", key="access_btn_prefill"):
            st.session_state.access_app   = _EX_ACCESS["app_name"]
            st.session_state.access_level = _EX_ACCESS["access_level"]
            st.session_state.access_just  = _EX_ACCESS["justification"]
            st.session_state.access_mgr   = _EX_ACCESS["manager"]

        app_name = st.text_input(
            "Application", key="access_app",
            placeholder="e.g. Salesforce, AWS, GitHub",
        )
        access_level = st.selectbox("Access Level", _ACCESS, key="access_level")
        justification = st.text_area(
            "Justification", key="access_just",
            height=120, max_chars=1000,
            placeholder="Why do you need this access?",
        )
        manager = st.text_input(
            "Manager Name", key="access_mgr",
            placeholder="Your direct manager",
        )

        if st.button("Assess Risk", type="primary", use_container_width=True,
                     key="access_submit", disabled=remaining == 0):
            if not app_name or not justification or not manager:
                st.warning("Application, justification, and manager are required.")
            elif rate_limit.is_allowed(ip):
                rate_limit.record(ip)
                with st.spinner("Claude is assessing risk..."):
                    try:
                        st.session_state.access_result = run_risk(
                            app_name, access_level, justification, manager
                        )
                    except Exception as e:
                        st.error(f"Error: {e}")

        if remaining == 0:
            st.error(f"Daily limit reached ({rate_limit.DAILY_LIMIT}/IP/day). Try again tomorrow.")
        else:
            st.caption(f"{remaining} of {rate_limit.DAILY_LIMIT} requests remaining today")

    with right:
        st.subheader("Risk Assessment")
        result = st.session_state.access_result
        if result:
            risk = result.get("risk_level", "")
            rec = result.get("recommendation", "")
            auto_approve = result.get("auto_approve", False)
            sox = result.get("sox_sensitive", False)

            alert_fn = {"High": st.error, "Medium": st.warning, "Low": st.success}.get(
                risk, st.info
            )
            alert_fn(f"**{risk} Risk** — {rec}")

            c1, c2 = st.columns(2)
            c1.metric("Recommendation", rec)
            c2.metric("SOX Sensitive", "Yes 🔒" if sox else "No")

            st.info(f"**Rationale**\n\n{result.get('rationale', '')}")

            factors = result.get("risk_factors", [])
            if factors:
                st.markdown("**Risk Factors:**")
                for f in factors:
                    st.markdown(f"- {f}")

            st.divider()
            if auto_approve:
                st.success("✅ **Auto-approve eligible** — low risk, justification verified")
            else:
                st.warning("🔄 **Routes to #it-approvals** for manager review")

            st.download_button(
                "Download JSON",
                data=json.dumps(result, indent=2),
                file_name="risk_assessment.json",
                mime="application/json",
                key="access_download",
            )
        else:
            st.markdown("*Submit a request on the left to see the risk assessment here.*")


# ═══════════════════════════════════════════════════════════════════════════════
# Tab 3 — /incident
# ═══════════════════════════════════════════════════════════════════════════════
with tab_incident:
    left, right = st.columns([4, 6])

    with left:
        st.subheader("Incident Declaration")
        if st.button("Pre-fill with example", key="inc_btn_prefill"):
            st.session_state.inc_title    = _EX_INCIDENT["title"]
            st.session_state.inc_severity = _EX_INCIDENT["severity"]
            st.session_state.inc_systems  = _EX_INCIDENT["systems"]
            st.session_state.inc_desc     = _EX_INCIDENT["description"]

        title = st.text_input(
            "Title", key="inc_title",
            placeholder="One-line incident summary",
        )
        severity = st.selectbox("Severity", _SEVERITY, key="inc_severity")
        systems = st.text_input(
            "Systems Affected", key="inc_systems",
            placeholder="e.g. api-gateway, postgres, auth-service",
        )
        description = st.text_area(
            "Description", key="inc_desc",
            height=160, max_chars=2000,
            placeholder="What's happening? What have you observed?",
        )

        if st.button("Declare Incident", type="primary", use_container_width=True,
                     key="inc_submit", disabled=remaining == 0):
            if not title or not description:
                st.warning("Title and description are required.")
            elif rate_limit.is_allowed(ip):
                rate_limit.record(ip)
                with st.spinner("Claude is assessing the incident..."):
                    try:
                        st.session_state.incident_result = run_incident(
                            title, systems, description, severity
                        )
                    except Exception as e:
                        st.error(f"Error: {e}")

        if remaining == 0:
            st.error(f"Daily limit reached ({rate_limit.DAILY_LIMIT}/IP/day). Try again tomorrow.")
        else:
            st.caption(f"{remaining} of {rate_limit.DAILY_LIMIT} requests remaining today")

    with right:
        st.subheader("Incident Assessment")
        result = st.session_state.incident_result
        if result:
            sev_val = st.session_state.get("inc_severity", _SEVERITY[0])
            st.error(f"🚨 **{sev_val} Declared**")

            st.info(f"**Summary**\n\n{result.get('summary', '')}")

            c1, c2 = st.columns(2)
            c1.metric("User Impact", result.get("user_impact", ""))
            c2.metric("Estimated Scope", result.get("estimated_scope", ""))

            actions = result.get("immediate_actions", [])
            if actions:
                st.markdown("**Immediate Actions:**")
                for i, action in enumerate(actions, 1):
                    st.markdown(f"{i}. {action}")

            teams = result.get("notify_teams", [])
            if teams:
                st.markdown("**Notify:** " + "  ".join(f"`{t}`" for t in teams))

            st.divider()
            st.download_button(
                "Download JSON",
                data=json.dumps(result, indent=2),
                file_name="incident_assessment.json",
                mime="application/json",
                key="inc_download",
            )
        else:
            st.markdown("*Declare an incident on the left to see the assessment here.*")
