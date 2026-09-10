"""Streamlit entry point. Run: streamlit run app.py"""

import html
import logging
import os
from datetime import datetime

import streamlit as st

st.set_page_config(page_title="Briefly · Meeting intelligence", page_icon="✳", layout="wide", initial_sidebar_state="expanded")

SECRET_KEYS = (
    "APP_ENV", "DATABASE_URL", "MISTRAL_API_KEY", "MISTRAL_MODEL", "SARVAM_API_KEY",
    "SARVAM_MODEL", "TRANSCRIPTION_BACKEND", "WHISPER_MODEL", "WHISPER_ALLOW_DOWNLOAD",
    "WHISPER_DEVICE", "WHISPER_COMPUTE_TYPE", "ALLOW_SIGNUP", "AUTH_MODE",
    "OIDC_ALLOWED_DOMAINS", "BRIEFLY_EMBEDDED_WORKER",
)
try:
    for key in SECRET_KEYS:
        if key in st.secrets:
            os.environ[key] = str(st.secrets[key])
except FileNotFoundError:
    pass

from briefly.service import Service  # noqa: E402

LOG = logging.getLogger("briefly.ui")
st.markdown("""<style>
:root{--ink:#193330;--muted:#6c7e76;--line:#dce4dc;--green:#12766a}
.stApp{background:#f8f9f6}
.block-container{padding-top:2.8rem;padding-bottom:4rem;max-width:1320px}
[data-testid="stSidebar"]{background:#eaf0e9;border-right:1px solid #d9e2d8}
[data-testid="stSidebar"] .block-container{padding-top:2rem}
h1,h2,h3{font-weight:550!important;letter-spacing:-.045em!important;color:var(--ink)!important}
h1{font-size:2.5rem!important;line-height:1.13!important} h2{font-size:1.75rem!important}
.brand{display:flex;gap:10px;align-items:center;font-weight:700;font-size:27px;letter-spacing:-1.2px;margin-bottom:6px}
.brand-icon{background:#1b7564;color:#f8fff4;display:inline-flex;width:35px;height:35px;align-items:center;justify-content:center;border-radius:11px;font-size:29px;letter-spacing:0}
.eyebrow{color:#688273;font-size:11px;font-weight:700;letter-spacing:2px;text-transform:uppercase;margin-bottom:13px}
.muted{color:#718279;font-size:13px;line-height:1.6}
.hero{background:#193d35;color:#f0f5eb;border-radius:20px;padding:32px 34px;position:relative;overflow:hidden;margin:12px 0 28px}
.hero h2{color:#f2f5e9!important;font-size:2rem!important;max-width:650px;margin:0 0 10px}
.hero p{color:#c6d9ca;max-width:630px;margin:0;font-size:14px;line-height:1.7}
.hero .eyebrow{color:#b4d6a8}
.hero-orbit{position:absolute;right:-40px;top:-80px;width:310px;height:310px;border:1px solid #557562;border-radius:50%;opacity:.6}
.hero-orbit:after{content:'';position:absolute;inset:35px;border:1px solid #769675;border-radius:50%}
.wave{display:flex;align-items:center;gap:4px;height:60px;margin:25px 0}
.wave span{width:5px;background:#aac89c;border-radius:7px;display:block}
.badge{display:inline-block;border-radius:99px;padding:4px 10px;font-size:11px;font-weight:650;letter-spacing:.3px;background:#edf3eb;color:#48765d}
.badge-ready{background:#e5f3e9;color:#24724d}.badge-queued,.badge-processing{background:#fff0dc;color:#986124}.badge-failed{background:#fbeae6;color:#9f503c}
.meeting-title{font-size:17px;font-weight:650;letter-spacing:-.35px;margin:6px 0 5px;color:#213e36}
.metric-label{color:#728278;font-size:12px;margin-bottom:7px}.metric-value{font-size:31px;font-weight:550;letter-spacing:-1px;color:#214535}
.section-label{font-size:11px;letter-spacing:1.6px;color:#7a8d7c;margin:25px 0 10px;text-transform:uppercase}
[data-testid="stVerticalBlockBorderWrapper"]>div{border-color:#dce5d9!important;border-radius:15px!important}
.stButton>button,.stDownloadButton>button{border-radius:9px;min-height:39px;font-size:13px}
.stTextInput input,.stTextArea textarea{font-size:14px}
.stTabs [data-baseweb="tab-list"]{gap:24px;margin-bottom:12px}.stTabs [data-baseweb="tab"]{font-size:13px}
.citation{padding:12px 15px;border-left:3px solid #8dab87;background:#eff3ec;border-radius:0 8px 8px 0;margin:8px 0;font-size:13px;line-height:1.65;white-space:pre-wrap;overflow-wrap:anywhere}
.quote{font-size:14px;line-height:1.8;padding:10px 0;color:#355145;overflow-wrap:anywhere}
.divider{height:1px;background:#dce5d9;margin:20px 0}
.empty{border:1px dashed #bfd0bd;border-radius:16px;padding:40px 28px;text-align:center;margin:20px 0;background:#f3f6ef}
.empty h3{font-size:22px!important;margin:0 0 10px}
.footnote{margin-top:30px;font-size:11px;line-height:1.8;color:#81907f}
[data-testid="stMetric"]{background:#fff;border:1px solid #dfe7dd;border-radius:13px;padding:17px}
@media(max-width:700px){.block-container{padding:2rem 1rem}.hero{padding:25px}.hero-orbit{display:none}h1{font-size:2rem!important}}
</style>""", unsafe_allow_html=True)


def esc(value):
    return html.escape(str(value))


def paragraph(value, css="quote"):
    st.markdown(f'<div class="{css}">{esc(value)}</div>', unsafe_allow_html=True)


def badge(status):
    safe = status if status in {"ready", "queued", "processing", "failed"} else "queued"
    st.markdown(f'<span class="badge badge-{safe}">{esc(status.capitalize())}</span>', unsafe_allow_html=True)


def human_date(value):
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y")
    try:
        return datetime.fromisoformat(str(value)).strftime("%d %b %Y")
    except ValueError:
        return str(value)[:16]


def source_label(value):
    return {"transcript": "Transcript", "youtube": "YouTube captions", "audio": "Audio recording", "video": "Video recording"}.get(value, value)


def navigate(page, meeting_id=None):
    st.session_state.page = page
    if meeting_id:
        st.session_state.meeting_id = meeting_id
    st.rerun()


def flash(message):
    st.session_state.notice = message


@st.cache_resource
def get_service():
    service = Service()
    service.start_worker()
    return service


def authenticate(service):
    left, gap, right = st.columns([1.2, .12, 1])
    with left:
        st.markdown('<div class="brand"><span class="brand-icon">✳</span>briefly</div>', unsafe_allow_html=True)
        st.markdown('<div class="eyebrow" style="margin-top:60px">A little less meeting. A lot more meaning.</div>', unsafe_allow_html=True)
        st.title("Good conversations.\nClear next steps.")
        st.markdown("Turn recordings into a shared understanding. Find the decisions, keep track of commitments, and ask questions with the source in view.")
        heights = [14, 23, 39, 25, 53, 37, 19, 44, 60, 35, 20, 42, 53, 29, 16, 35, 49, 21, 40, 58, 34, 16, 29, 47, 23]
        st.markdown('<div class="wave">' + ''.join(f'<span style="height:{h}px"></span>' for h in heights) + '</div>', unsafe_allow_html=True)
        for title, description in [("01  Bring the conversation", "Import a transcript, YouTube captions, or an audio/video recording."), ("02  Find what matters", "Review source-backed highlights, decisions and action items."), ("03  Keep things moving", "Ask questions, complete actions, and share a meeting report.")]:
            st.markdown(f"**{title}**")
            st.caption(description)
    with right:
        st.markdown('<div style="height:48px"></div>', unsafe_allow_html=True)
        with st.container(border=True):
            st.subheader("Your meeting workspace")
            st.caption("Sign in to pick up where the conversation left off.")
            if service.auth_mode == "oidc":
                if st.user.is_logged_in:
                    st.session_state.user = service.oidc_login(dict(st.user))
                    st.rerun()
                if st.button("Continue with organization SSO", type="primary", width="stretch"):
                    st.login()
            else:
                tabs = st.tabs(["Sign in", "Create account"] if service.signup_allowed else ["Sign in"])
                with tabs[0]:
                    with st.form("login"):
                        username = st.text_input("Username or email", autocomplete="username")
                        password = st.text_input("Password", type="password", autocomplete="current-password")
                        submit = st.form_submit_button("Sign in →", type="primary", width="stretch")
                    if submit:
                        st.session_state.user = service.login(username, password)
                        st.session_state.page = "library"
                        st.rerun()
                if service.signup_allowed:
                    with tabs[1]:
                        with st.form("signup"):
                            name = st.text_input("Username", help="3–40 letters, numbers, dots, underscores or dashes.")
                            email = st.text_input("Email", autocomplete="email")
                            workspace = st.text_input("Workspace name", placeholder="Your team's workspace")
                            password = st.text_input("Choose a password", type="password", help="Use at least 12 characters.")
                            repeat = st.text_input("Confirm password", type="password")
                            register = st.form_submit_button("Create your workspace", type="primary", width="stretch")
                        if register:
                            if password != repeat:
                                raise ValueError("Passwords do not match.")
                            st.session_state.user = service.register(name, email, password, workspace)
                            st.session_state.page = "library"
                            st.rerun()
            if not service.production:
                st.divider()
                st.caption("Take a look around with a private sample workspace.")
                if st.button("Explore the demo", width="stretch"):
                    st.session_state.user = service.demo_login()
                    st.session_state.page = "library"
                    st.rerun()
                st.caption("Sample content only. Demo workspaces use this installation's local database.")
        paragraph(service.capabilities()["provider_mode"], "muted")


def sidebar(service, user):
    with st.sidebar:
        st.markdown('<div class="brand"><span class="brand-icon">✳</span>briefly</div><div class="muted">Meeting intelligence</div>', unsafe_allow_html=True)
        st.markdown('<div class="divider"></div>', unsafe_allow_html=True)
        spaces = service.workspaces(user)
        current = next(space for space in spaces if space["id"] == user["workspace_id"])
        user["role"] = current["role"]
        if len(spaces) > 1:
            selected = st.selectbox("Workspace", spaces, index=spaces.index(current), format_func=lambda x: x["name"])
            if selected["id"] != current["id"]:
                st.session_state.user = service.switch_workspace(user, selected["id"])
                st.session_state.pop("prepared_export", None)
                navigate("library")
        else:
            paragraph(current["name"], "meeting-title")
        paragraph(current["role"].capitalize() + " access", "muted")
        st.markdown('<div class="section-label">Workspace</div>', unsafe_allow_html=True)
        page = st.session_state.get("page", "library")
        for label, target, icon in [("Meeting library", "library", ":material/library_books:"), ("Action items", "actions", ":material/task_alt:"), ("Team", "team", ":material/group:")]:
            if st.button(label, icon=icon, type="primary" if page == target else "secondary", width="stretch"):
                navigate(target)
        st.markdown('<div class="section-label">Manage</div>', unsafe_allow_html=True)
        if user["role"] == "owner" and st.button("Activity log", icon=":material/history:", width="stretch"):
            navigate("audit")
        if st.button("Settings", icon=":material/tune:", width="stretch"):
            navigate("settings")
        st.markdown('<div style="height:70px"></div>', unsafe_allow_html=True)
        paragraph(user["email"] if not user.get("demo") else "Exploring a private demo", "muted")
        if st.button("Sign out", icon=":material/logout:", width="stretch"):
            service.logout(user)
            st.session_state.clear()
            if service.auth_mode == "oidc" and st.user.is_logged_in:
                st.logout()
            st.rerun()
        st.markdown('<div class="footnote">Thoughtfully organized.<br>Always connected to the source.</div>', unsafe_allow_html=True)


def library(service, user):
    top, button = st.columns([4, 1])
    with top:
        st.markdown('<div class="eyebrow">Your team’s shared memory</div>', unsafe_allow_html=True)
        st.title("Meeting library")
    with button:
        st.write("")
        if st.button("New meeting", icon=":material/add:", type="primary", width="stretch", disabled=user["role"] == "viewer"):
            navigate("new")
    st.markdown('<div class="hero"><div class="hero-orbit"></div><div class="eyebrow">From conversation to clarity</div><h2>Leave the meeting.<br>Keep the momentum.</h2><p>Decisions, commitments and the context behind them.<br>All your conversations, ready to work with.</p></div>', unsafe_allow_html=True)
    meetings = service.list_meetings(user)
    actions = service.list_actions(user)
    metrics = [("Meetings", len(meetings)), ("Ready to explore", sum(m["status"] == "ready" for m in meetings)), ("Open action items", sum(a["status"] == "open" for a in actions)), ("Processing", sum(m["status"] in {"processing", "queued"} for m in meetings))]
    for column, (label, value) in zip(st.columns(4), metrics):
        with column:
            st.metric(label, value)
    st.write("")
    search, status = st.columns([3, 1])
    with search:
        query = st.text_input("Search your meetings", placeholder="Search by meeting title…", label_visibility="collapsed")
    with status:
        selected_status = st.selectbox("Filter by status", ["All statuses", "Ready", "Queued", "Processing", "Failed"], label_visibility="collapsed")
    filtered = [m for m in meetings if query.casefold() in m["title"].casefold() and (selected_status == "All statuses" or m["status"] == selected_status.lower())]
    st.markdown('<div class="section-label">Recent conversations</div>', unsafe_allow_html=True)
    if not filtered:
        st.markdown('<div class="empty"><h3>A clear space for your next conversation.</h3><p>Import a meeting to create your first set of highlights and follow-ups.</p></div>', unsafe_allow_html=True)
        if not meetings and user["role"] != "viewer" and st.button("Start with a sample meeting", icon=":material/auto_awesome:"):
            mid = service.sample_meeting(user)
            navigate("detail", mid)
    for meeting in filtered:
        with st.container(border=True):
            content, state, open_column = st.columns([5, 1.25, 1.1], vertical_alignment="center")
            with content:
                paragraph(meeting["title"], "meeting-title")
                paragraph(f"{source_label(meeting['source_type'])}  ·  {human_date(meeting['created_at'])}  ·  {meeting['language'].upper()}", "muted")
                if meeting["summary"]:
                    paragraph(meeting["summary"][0][:180] + ("…" if len(meeting["summary"][0]) > 180 else ""), "muted")
            with state:
                badge(meeting["status"])
            with open_column:
                if st.button("Open →", key="open_" + meeting["id"], width="stretch"):
                    navigate("detail", meeting["id"])
    if any(m["status"] in {"queued", "processing"} for m in meetings):
        st.caption("Your meeting is being processed in the background.")
        if st.button("Refresh processing status", icon=":material/refresh:"):
            st.rerun()


def create_meeting(service, user):
    if st.button("← Back to library"):
        navigate("library")
    st.markdown('<div class="eyebrow">Bring the conversation</div>', unsafe_allow_html=True)
    st.title("A new meeting, made clear.")
    st.caption("Add your source. Briefly will organize the highlights, decisions and follow-ups.")
    left, right = st.columns([2, 1])
    with left:
        kind = st.radio("Choose your source", ["Transcript", "YouTube", "Audio / video"], horizontal=True)
        with st.form("new_meeting"):
            title = st.text_input("Meeting title", max_chars=160, placeholder="e.g. Product launch review")
            language_label = st.selectbox("Language", ["Automatic", "English", "Hindi", "Hinglish"])
            language = {"Automatic": "auto", "English": "en", "Hindi": "hi", "Hinglish": "hinglish"}[language_label]
            transcript, source_url, source_file = "", "", None
            if kind == "Transcript":
                transcript = st.text_area("Meeting transcript", height=270, placeholder="[00:00] Maya: Let's review the launch plan…\n[00:30] Arjun: I will finish testing by Friday.")
                text_file = st.file_uploader("Or upload a transcript", type=["txt", "srt", "vtt"])
                st.caption("At least 40 characters; text files up to 20 MB. Long transcripts are processed in batches. Timestamps and speaker names help preserve context.")
            elif kind == "YouTube":
                source_url = st.text_input("YouTube video URL", placeholder="https://www.youtube.com/watch?v=…")
                st.caption("Imports available captions. Restricted videos and videos without captions need a transcript instead.")
            else:
                source_file = st.file_uploader("Audio or video file", type=["wav", "mp3", "m4a", "mp4", "webm", "ogg", "flac"])
                st.caption("Up to 200 MB and 12 hours. Sarvam requires PCM WAV; Whisper supports the listed media formats.")
                if not service.capabilities()["audio_enabled"]:
                    st.info("Audio transcription needs an operator to configure Whisper or Sarvam. Transcript and YouTube imports are available now.")
            submitted = st.form_submit_button("Create meeting →", type="primary", width="stretch", disabled=user["role"] == "viewer" or (kind == "Audio / video" and not service.capabilities()["audio_enabled"]))
        if submitted:
            if kind == "Transcript":
                if text_file is not None:
                    if text_file.size > 20 * 1024 * 1024:
                        raise ValueError("Transcript files must be up to 20 MB.")
                    try:
                        transcript = text_file.getvalue().decode("utf-8-sig")
                    except UnicodeDecodeError:
                        raise ValueError("Save the transcript as UTF-8 and try again.") from None
                source_type = "transcript"
            elif kind == "YouTube":
                source_type = "youtube"
            else:
                if source_file is None:
                    raise ValueError("Choose an audio or video file.")
                source_type = "video" if source_file.name.lower().endswith((".mp4", ".webm")) else "audio"
            mid = service.create_meeting(user, title, source_type, transcript=transcript, source_url=source_url, file_bytes=source_file.getvalue() if source_file else None, filename=source_file.name if source_file else "", language=language)
            flash("Meeting added. Processing has started.")
            navigate("detail", mid)
    with right:
        with st.container(border=True):
            st.subheader("A few useful details")
            st.markdown("**Keep the context**\n\nInclude speaker names and timestamps when you have them.")
            st.markdown("**Review the output**\n\nHighlights and action items are grounded in the transcript. Check dates and owners before acting.")
            st.markdown("**Your workspace**\n\nOnly members of this workspace can access its meetings.")
            paragraph(service.capabilities()["provider_mode"], "muted")
            if os.getenv("MISTRAL_API_KEY"):
                st.caption("Transcript evidence is sent to Mistral for analysis. Audio uses the configured transcription provider.")


@st.fragment(run_every=3)
def processing_status(service, user, mid, initial_status):
    meeting = service.get_meeting(user, mid)
    if meeting["status"] != initial_status:
        st.rerun()
    st.info("Waiting for a worker…" if meeting["status"] == "queued" else "Finding the highlights, decisions and next steps…")
    st.caption("You can leave this page. Processing continues while the app is running.")


def page_items(items, key, size=20):
    if len(items) <= size:
        return items
    pages = (len(items) + size - 1) // size
    page = int(st.number_input("Page", min_value=1, max_value=pages, value=1, step=1, key=key + "_page"))
    st.caption(f"Page {page} of {pages} · {len(items):,} results")
    return items[(page - 1) * size:page * size]


def render_actions(service, user, actions, key_prefix):
    if not actions:
        st.info("No explicit action items were found. Nothing to track yet.")
    for action in page_items(actions, key_prefix, 25):
        with st.container(border=True):
            body, toggle = st.columns([5, 1], vertical_alignment="center")
            with body:
                paragraph(action["text"])
                paragraph(f"{action['owner'] or 'Unassigned'}  ·  {action['deadline'] or 'No deadline stated'}", "muted")
                if action.get("meeting_title"):
                    paragraph(action["meeting_title"], "muted")
            with toggle:
                if st.button("Reopen" if action["status"] == "done" else "Complete", key=key_prefix + action["id"], disabled=user["role"] == "viewer", width="stretch"):
                    service.toggle_action(user, action["id"])
                    st.rerun()
            with st.expander("Source evidence"):
                paragraph(action["evidence"], "citation")


def detail(service, user):
    mid = st.session_state.get("meeting_id")
    meeting = service.get_meeting(user, mid)
    if st.button("← Meeting library"):
        navigate("library")
    badge(meeting["status"])
    st.markdown(f"<h1>{esc(meeting['title'])}</h1>", unsafe_allow_html=True)
    paragraph(f"{source_label(meeting['source_type'])}  ·  {human_date(meeting['created_at'])}  ·  {meeting['language'].upper()}", "muted")
    if meeting["status"] in {"queued", "processing"}:
        processing_status(service, user, mid, meeting["status"])
    elif meeting["status"] == "failed":
        st.error(meeting["error"])
        if user["role"] != "viewer" and st.button("Retry processing", type="primary"):
            service.retry_meeting(user, mid)
            st.rerun()
    else:
        mode = "Mistral · verified source quotations" if meeting["analysis_mode"] == "mistral" else "Extractive analysis · source quotations, no language model"
        st.caption(mode)
        overview, actions_tab, transcript_tab, chat_tab, export_tab = st.tabs(["Overview", f"Action items ({len(meeting['actions'])})", "Transcript", "Ask this meeting", "Export"])
        with overview:
            main, aside = st.columns([1.7, 1])
            with main:
                st.subheader("The conversation, distilled.")
                if not meeting["summary"]:
                    st.info("No verifiable highlights were found.")
                for index, item in enumerate(meeting["summary"], 1):
                    with st.container(border=True):
                        st.caption(f"HIGHLIGHT {index:02d}")
                        paragraph(item)
            with aside:
                with st.container(border=True):
                    st.subheader("Decisions")
                    for item in page_items(meeting["decisions"], "decisions_" + mid):
                        paragraph(item)
                    if not meeting["decisions"]:
                        st.caption("No explicit decisions found.")
                with st.container(border=True):
                    st.subheader("Still open")
                    for item in page_items(meeting["questions"], "questions_" + mid):
                        paragraph(item)
                    if not meeting["questions"]:
                        st.caption("No explicit open questions found.")
        with actions_tab:
            st.subheader("Turn commitments into progress.")
            st.caption("Owners and deadlines preserve what was said. Unstated details remain unassigned.")
            render_actions(service, user, meeting["actions"], "detail_action_")
        with transcript_tab:
            find = st.text_input("Find in transcript", placeholder="Search for a phrase…")
            segments = [c for c in meeting["chunks"] if find.casefold() in c["text"].casefold()]
            st.caption(f"{len(segments)} segments · segment numbers match answer citations")
            for chunk in page_items(segments, "transcript_" + mid + find, 50):
                time = int(chunk.get("start") or 0)
                label = f"{time // 60:02d}:{time % 60:02d}" if time else "Source"
                st.markdown(f"**[{chunk['index'] + 1}] · {label}**")
                paragraph(chunk["text"])
        with chat_tab:
            st.subheader("Ask. Find. Know why.")
            st.caption("Answers include transcript excerpts you can check. If there is no supporting evidence, Briefly will say so.")
            suggestions = st.columns(3)
            for column, prompt in zip(suggestions, ["What was decided?", "What are the action items?", "What risks were discussed?"]):
                with column:
                    if st.button(prompt, key="suggest_" + prompt, width="stretch"):
                        with st.spinner("Finding supporting evidence…"):
                            service.ask(user, mid, prompt)
                        st.rerun()
            for chat in meeting["chats"]:
                with st.chat_message("user"):
                    paragraph(chat["question"])
                with st.chat_message("assistant"):
                    # Display untrusted content as escaped text, never interpreted Markdown.
                    paragraph(chat["answer"])
                    for citation in chat["citations"]:
                        time = int(citation.get("start") or 0)
                        st.caption(f"Source [{citation['index'] + 1}]" + (f" · {time // 60:02d}:{time % 60:02d}" if time else ""))
                        paragraph(citation["text"], "citation")
                    st.caption("Extractive search" if chat["mode"] == "extractive" else "Mistral · verified quotations")
            with st.form("ask_meeting", clear_on_submit=True):
                question = st.text_input("Your question", placeholder="What does Priya need to finish?", max_chars=1000)
                ask = st.form_submit_button("Ask meeting →", type="primary")
            if ask:
                with st.spinner("Finding supporting evidence…"):
                    service.ask(user, mid, question)
                st.rerun()
        with export_tab:
            st.subheader("Keep everyone on the same page.")
            st.caption("Export the highlights, action items, decisions and full transcript.")
            fmt = st.radio("Report format", ["PDF", "TXT", "JSON"], horizontal=True)
            if st.button("Prepare report", icon=":material/download:", type="primary"):
                st.session_state.prepared_export = {"meeting_id": mid, "format": fmt.lower(), "data": service.export_meeting(user, mid, fmt.lower())}
            prepared = st.session_state.get("prepared_export")
            if prepared and prepared["meeting_id"] == mid and prepared["format"] == fmt.lower():
                st.download_button("Download " + fmt + " report", prepared["data"], file_name="briefly-meeting-" + mid[:8] + "." + fmt.lower(), mime={"PDF": "application/pdf", "TXT": "text/plain", "JSON": "application/json"}[fmt])
    if user["role"] == "owner":
        st.divider()
        with st.expander("Meeting management"):
            confirm = st.checkbox("Archive this meeting and remove it from the workspace library")
            st.caption("An operator can restore an archived meeting for 30 days before scheduled maintenance purges it.")
            if st.button("Archive meeting", disabled=not confirm):
                service.delete_meeting(user, mid)
                flash("Meeting archived.")
                navigate("library")


def actions_page(service, user):
    st.markdown('<div class="eyebrow">Keep the momentum</div>', unsafe_allow_html=True)
    st.title("Action items")
    st.caption("The commitments made across your workspace, together in one place.")
    actions = service.list_actions(user)
    status = st.radio("Show actions", ["Open", "Completed", "All"], horizontal=True)
    selected = [a for a in actions if status == "All" or a["status"] == ("open" if status == "Open" else "done")]
    render_actions(service, user, selected, "workspace_action_")


def team_page(service, user):
    st.markdown('<div class="eyebrow">Better together</div>', unsafe_allow_html=True)
    st.title("Your team")
    st.caption("Owners manage the workspace. Editors import meetings and track actions. Viewers can read and ask questions.")
    for member in service.members(user):
        with st.container(border=True):
            name, role, control = st.columns([4, 1, 1])
            with name:
                paragraph(member["email"], "meeting-title")
                paragraph(member["username"], "muted")
            with role:
                paragraph(member["role"].capitalize(), "muted")
            with control:
                if user["role"] == "owner" and member["role"] != "owner":
                    if st.button("Remove", key="remove_" + member["id"]):
                        service.remove_member(user, member["id"])
                        st.rerun()
    if user["role"] == "owner":
        st.subheader("Add a teammate")
        st.caption("Your teammate must sign in first. Add their registered email; no invitation email is sent.")
        with st.form("add_member"):
            email = st.text_input("Teammate's email")
            role = st.selectbox("Workspace role", ["Editor", "Viewer"])
            add = st.form_submit_button("Add or update teammate", type="primary")
        if add:
            service.add_member(user, email, role.lower())
            flash("Team access updated.")
            st.rerun()


def audit_page(service, user):
    st.markdown('<div class="eyebrow">Workspace history</div>', unsafe_allow_html=True)
    st.title("Activity log")
    st.caption("Recent access and workflow events. Transcript content and credentials are excluded.")
    events = service.audit(user)
    if events:
        st.dataframe([{ "When (UTC)": e["created_at"], "Event": e["event"], "Actor": e["actor"], "Reference": e["resource_id"]} for e in events], hide_index=True, width="stretch")
    else:
        st.info("Activity will appear as your workspace is used.")


def settings_page(service, user):
    st.markdown('<div class="eyebrow">Your workspace, configured</div>', unsafe_allow_html=True)
    st.title("Settings")
    capabilities = service.capabilities()
    for title, key in [("Meeting analysis", "provider_mode"), ("Audio transcription", "transcription_mode"), ("Data storage", "persistence_mode")]:
        with st.container(border=True):
            st.subheader(title)
            paragraph(capabilities[key])
    st.caption("Provider credentials are managed by the operator in server secrets. They are never entered into meeting prompts.")
    if not service.production:
        st.info("This is a local development installation. Use production configuration and external PostgreSQL for a durable cloud workspace.")
    st.subheader("Data and access")
    st.markdown("Meetings are isolated by workspace. Sessions expire after eight hours. Owners can archive meetings; an operator can recover them for 30 days. Uploaded media is removed after successful transcription.")
    if user["role"] == "owner":
        st.caption("Production team membership requires verified organization SSO. See the deployment guide for identity-provider configuration.")


def main():
    try:
        service = get_service()
    except Exception as exc:
        LOG.error("startup_failed error_type=%s", type(exc).__name__)
        st.title("Briefly needs a little setup")
        st.error(str(exc) if isinstance(exc, ValueError) else "The database could not be initialized. Check the server configuration and migration logs.")
        st.info("For Streamlit Community Cloud, configure APP_ENV and DATABASE_URL in app secrets. See docs/DEPLOYMENT.md in the project.")
        st.stop()
    try:
        user = st.session_state.get("user")
        if not user:
            authenticate(service)
            return
        sidebar(service, user)
        if "notice" in st.session_state:
            st.success(st.session_state.pop("notice"))
        page = st.session_state.get("page", "library")
        pages = {"library": library, "new": create_meeting, "detail": detail, "actions": actions_page, "team": team_page, "audit": audit_page, "settings": settings_page}
        pages.get(page, library)(service, user)
    except ValueError as exc:
        st.error(str(exc))
        if "session" in str(exc).lower() or "access to this workspace" in str(exc).lower():
            if st.button("Return to sign in"):
                st.session_state.clear()
                st.rerun()
    except Exception as exc:
        LOG.error("ui_operation_failed error_type=%s", type(exc).__name__)
        st.error("This operation could not be completed. Try again, or contact your workspace operator.")


if __name__ == "__main__":
    main()
