import gradio as gr
import requests

API_URL = "https://api.nanai.khoofia.com"

def analyze_media(prompt, file):
    if not file:
        return "No file uploaded."
    try:
        with open(file, "rb") as f:
            response = requests.post(f"{API_URL}/analyze", data={"prompt": prompt}, files={"file": f})
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return f"Error: {str(e)}"

def translate_wrapper(prompt):
    try:
        response = requests.post(f"{API_URL}/translate", json={"prompt": prompt})
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}

# --- API Fetch Wrappers ---
def get_rules_df():
    try:
        resp = requests.get(f"{API_URL}/rules")
        return [
            [r["id"], r["name"], r.get("description", ""), r["enabled"], r.get("schedule_cron", ""), r.get("cool_off_minutes", 0), r.get("max_daily_triggers", 0)]
            for r in resp.json()
        ]
    except Exception:
        return []

def get_contexts_wrapper(r_id):
    if not r_id: return []
    try:
        resp = requests.get(f"{API_URL}/rules/{int(r_id)}/contexts")
        resp.raise_for_status()
        return [
            [c["id"], c["context_type"], c.get("start_time", ""), c.get("end_time", ""), c.get("room_name", "")]
            for c in resp.json()
        ]
    except Exception:
        return []

def get_sensors_df():
    try:
        resp = requests.get(f"{API_URL}/sensors")
        return [[s["id"], s["name"], s["room_name"], s["type"], s["enabled"]] for s in resp.json()]
    except Exception:
        return []

def get_event_logs_df():
    try:
        resp = requests.get(f"{API_URL}/admin/event_logs")
        return [
            [
                r["id"],
                r.get("timestamp"),
                r.get("rule_name", ""),
                r.get("sensor_id", ""),
                r.get("room_name", ""),
                r.get("media_path", ""),
                r.get("status", ""),
            ]
            for r in resp.json()
        ]
    except Exception:
        return []

def get_room_occupancy_df():
    try:
        resp = requests.get(f"{API_URL}/admin/room_occupancy")
        return [
            [
                r["id"],
                r.get("sensor_id", ""),
                r.get("room_name", ""),
                r.get("start_time"),
                r.get("end_time"),
                r.get("is_active", False),
            ]
            for r in resp.json()
        ]
    except Exception:
        return []

def get_emergency_alerts_df():
    try:
        resp = requests.get(f"{API_URL}/admin/emergency_alerts")
        return [
            [
                r["id"],
                r.get("timestamp"),
                r.get("alert_type", ""),
                r.get("description", ""),
                r.get("sensor_id", ""),
                r.get("room_name", ""),
                r.get("resolved", False),
                r.get("assistance_needed", False),
            ]
            for r in resp.json()
        ]
    except Exception:
        return []

def get_active_image_state_df():
    try:
        resp = requests.get(f"{API_URL}/admin/active_image_state")
        return [
            [
                r["id"],
                r.get("expires_at"),
            ]
            for r in resp.json()
        ]
    except Exception:
        return []

def _optional_bool(value):
    if value == "true":
        return True
    if value == "false":
        return False
    return None

def _select_int_id(evt: gr.SelectData):
    if isinstance(evt.value, (int, float)) and int(evt.value) == evt.value:
        return int(evt.value)
    return None

# --- UI Components ---
def create_vision_tab():
    with gr.Tab("Vision"):
        gr.Markdown("### Debug Vision Language Model")
        with gr.Row():
            with gr.Column(scale=1):
                prompt_input = gr.Textbox(label="Prompt", value="Describe this content.")
                file_input = gr.File(label="Upload Image or Video")
                analyze_btn = gr.Button("Analyze", variant="primary")
            with gr.Column(scale=2):
                output_json = gr.JSON(label="API Response")
        
        analyze_btn.click(fn=analyze_media, inputs=[prompt_input, file_input], outputs=output_json)

def create_translation_tab():
    with gr.Tab("Translation"):
        gr.Markdown("### Debug Translation Model")
        with gr.Row():
            with gr.Column(scale=1):
                trans_prompt = gr.Textbox(label="Text to Translate", placeholder="Enter Tamil text here...", lines=4)
                trans_btn = gr.Button("Translate", variant="primary")
            with gr.Column(scale=2):
                trans_output = gr.JSON(label="Translation Result")
                
        trans_btn.click(fn=translate_wrapper, inputs=trans_prompt, outputs=trans_output)

def create_rules_tab():
    with gr.Tab("Rule Management"):
        gr.Markdown("### Manage Automated Workflow Rules")
        
        with gr.Row():
            refresh_rules_btn = gr.Button("Refresh Rules", variant="secondary")
        
        rule_list = gr.DataFrame(
            headers=["ID", "Name", "Desc", "Enabled", "Cron", "Min Cooldown", "Max Triggers"], 
            datatype=["number", "str", "str", "bool", "str", "number", "number"], 
            label="Existing Rules", 
            interactive=False
        )
        
        with gr.Row():
            # Rule Editor Column
            with gr.Column(scale=1, variant="panel"):
                gr.Markdown("#### Create / Edit Rule")
                rule_id_input = gr.Number(label="Target Rule ID (Leave empty for Create)", precision=0)
                rule_name = gr.Textbox(label="Name", placeholder="e.g. Morning Check")
                rule_desc = gr.Textbox(label="Description", lines=2)
                rule_enabled = gr.Checkbox(label="Enabled", value=True)
                rule_cron = gr.Textbox(label="Cron Schedule", placeholder="e.g. 0 8 * * *")
                
                with gr.Accordion("Advanced Rule Settings", open=False):
                    rule_vision = gr.Textbox(label="Vision Prompt", value="Describe this image in detail.", lines=2)
                    rule_logic = gr.Textbox(label="Logic Prompt", value="Based on the description, decide if an action is needed.", lines=2)
                    gemini_live_prompt = gr.Textbox(label="Gemini Live Prompt", value="Prompt for Gemini Live response.", lines=2)
                    rule_feedback = gr.Textbox(label="Feedback Template", value="Notification: {result}", lines=2)
                    rule_cool = gr.Number(label="Cool Off Minutes", value=5, precision=0)
                    rule_max = gr.Number(label="Max Daily Triggers", value=3, precision=0)

                with gr.Row():
                    create_rule_btn = gr.Button("Save Rule", variant="primary")
                    delete_rule_btn = gr.Button("Delete Rule", variant="stop")
                rule_status_msg = gr.Textbox(label="Rule Status", interactive=False)

            # Context Editor Column
            with gr.Column(scale=1, variant="panel"):
                gr.Markdown("#### Context Management")
                target_rule_id = gr.Number(label="Target Rule ID for Contexts", precision=0)
                
                context_list = gr.DataFrame(headers=["ID", "Type", "Start", "End", "Room"], interactive=False)
                refresh_ctx_btn = gr.Button("View Contexts for Rule", variant="secondary")
                
                gr.Markdown("**Add Context**")
                ctx_type = gr.Dropdown(choices=["time_range", "room"], label="Context Type")
                with gr.Row():
                    ctx_start = gr.Textbox(label="Start (HH:MM)")
                    ctx_end = gr.Textbox(label="End (HH:MM)")
                    ctx_room = gr.Textbox(label="Room Name")
                add_ctx_btn = gr.Button("Add Context", variant="primary")
                
                gr.Markdown("**Delete Context**")
                with gr.Row():
                    ctx_id_to_delete = gr.Number(label="Context ID to Delete", precision=0)
                    del_ctx_btn = gr.Button("Delete Context", variant="stop")
                
                ctx_status = gr.Textbox(label="Context Status", interactive=False)

        # Event Handlers
        refresh_rules_btn.click(fn=get_rules_df, inputs=[], outputs=rule_list)
        
        def save_rule(r_id, name, desc, enabled, cron, v, l, g, f, cool, mx):
            try:
                payload = {"name": name, "description": desc, "enabled": enabled, "schedule_cron": cron, "vision_prompt": v, "logic_prompt": l, "gemini_live_prompt": g, "feedback_template": f, "cool_off_minutes": int(cool), "max_daily_triggers": int(mx)}
                if r_id and r_id > 0:
                    resp = requests.put(f"{API_URL}/rules/{int(r_id)}", json=payload)
                    resp.raise_for_status()
                    return "Rule Updated"
                else:
                    resp = requests.post(f"{API_URL}/rules", json=payload)
                    resp.raise_for_status()
                    return "Rule Created"
            except Exception as e:
                err_msg = str(e)
                if hasattr(e, 'response') and e.response is not None:
                    err_msg += f" - Response: {e.response.text}"
                return f"Error: {err_msg}"
                
        create_rule_btn.click(fn=save_rule, inputs=[rule_id_input, rule_name, rule_desc, rule_enabled, rule_cron, rule_vision, rule_logic, gemini_live_prompt, rule_feedback, rule_cool, rule_max], outputs=rule_status_msg).then(
            fn=get_rules_df, outputs=rule_list
        )
        
        def delete_rule(r_id):
            if not r_id: return "Enter Rule ID"
            try:
                requests.delete(f"{API_URL}/rules/{int(r_id)}").raise_for_status()
                return "Rule Deleted"
            except Exception as e:
                return f"Error: {e}"
                
        delete_rule_btn.click(fn=delete_rule, inputs=[rule_id_input], outputs=rule_status_msg).then(
            fn=get_rules_df, outputs=rule_list
        )
        
        refresh_ctx_btn.click(fn=get_contexts_wrapper, inputs=[target_rule_id], outputs=context_list)
        
        def add_context(r_id, c_type, start, end, room):
            if not r_id: return "Enter Target Rule ID"
            try:
                payload = {"context_type": c_type}
                if c_type == "time_range":
                    payload.update({"start_time": start, "end_time": end})
                elif c_type == "room":
                    payload["room_name"] = room
                requests.post(f"{API_URL}/rules/{int(r_id)}/context", json=payload).raise_for_status()
                return "Context Added"
            except Exception as e:
                return f"Error: {e}"

        add_ctx_btn.click(fn=add_context, inputs=[target_rule_id, ctx_type, ctx_start, ctx_end, ctx_room], outputs=ctx_status).then(
            fn=get_contexts_wrapper, inputs=[target_rule_id], outputs=context_list
        )
        
        def delete_context(r_id, c_id):
            if not r_id or not c_id: return "Enter Rule and Context ID"
            try:
                requests.delete(f"{API_URL}/rules/{int(r_id)}/context/{int(c_id)}").raise_for_status()
                return "Context Deleted"
            except Exception as e:
                return f"Error: {e}"
        del_ctx_btn.click(fn=delete_context, inputs=[target_rule_id, ctx_id_to_delete], outputs=ctx_status).then(
            fn=get_contexts_wrapper, inputs=[target_rule_id], outputs=context_list
        )
        
        # Populate input forms from dataframe clicks mapping
        def select_rule(evt: gr.SelectData):
            # evt.value returns the cell value, evt.index is [row, col]
            # To be robust, the UI would need the whole row data. This is trickier in basic Gradio.
            # We will at least autofill the target ID based on the selected row.
            return evt.value if isinstance(evt.value, int) else None

        rule_list.select(fn=select_rule, outputs=rule_id_input)
        rule_list.select(fn=select_rule, outputs=target_rule_id)
        
def create_sensors_tab():
    with gr.Tab("Sensor Management"):
        gr.Markdown("### Manage Environment Sensors")
        refresh_sensors_btn = gr.Button("Refresh Sensors", variant="secondary")
        sensor_list = gr.DataFrame(headers=["ID", "Name", "Room", "Type", "Enabled"], interactive=False)
        
        with gr.Group():
            gr.Markdown("#### Input Form")
            with gr.Row():
                s_id = gr.Textbox(label="Sensor ID (e.g. recamera-001)")
                s_name = gr.Textbox(label="Name")
                s_room = gr.Textbox(label="Room Name")
                s_type = gr.Dropdown(choices=["camera", "presence", "button"], label="Type", value="camera")
                s_enabled = gr.Checkbox(label="Enabled", value=True)
                
            with gr.Row():
                create_sensor_btn = gr.Button("Create Sensor", variant="primary")
                update_sensor_btn = gr.Button("Update Sensor", variant="secondary")
                delete_sensor_btn = gr.Button("Delete Sensor", variant="stop")
                
            sensor_status = gr.Textbox(label="Status", interactive=False)

        refresh_sensors_btn.click(fn=get_sensors_df, outputs=sensor_list)
        
        def save_sensor(sid, name, room, stype, enabled, update=False):
            if not sid: return "Sensor ID required"
            try:
                payload = {"name": name, "room_name": room, "type": stype, "enabled": enabled}
                if update:
                    requests.put(f"{API_URL}/sensors/{sid}", json=payload).raise_for_status()
                    return "Sensor Updated"
                else:
                    payload["id"] = sid
                    requests.post(f"{API_URL}/sensors", json=payload).raise_for_status()
                    return "Sensor Created"
            except Exception as e:
                return f"Error: {e}"

        create_sensor_btn.click(fn=lambda sid, n, r, t, e: save_sensor(sid, n, r, t, e, False), inputs=[s_id, s_name, s_room, s_type, s_enabled], outputs=sensor_status).then(
            fn=get_sensors_df, outputs=sensor_list
        )
        update_sensor_btn.click(fn=lambda sid, n, r, t, e: save_sensor(sid, n, r, t, e, True), inputs=[s_id, s_name, s_room, s_type, s_enabled], outputs=sensor_status).then(
            fn=get_sensors_df, outputs=sensor_list
        )

        def delete_sensor(sid):
            if not sid: return "Sensor ID required"
            try:
                requests.delete(f"{API_URL}/sensors/{sid}").raise_for_status()
                return "Sensor Deleted"
            except Exception as e:
                return f"Error: {e}"
        delete_sensor_btn.click(fn=delete_sensor, inputs=[s_id], outputs=sensor_status).then(
            fn=get_sensors_df, outputs=sensor_list
        )

def create_admin_tab():
    with gr.Tab("Admin Data"):
        gr.Markdown("### Admin: Logs and State")

        with gr.Group():
            gr.Markdown("#### Event Logs")
            refresh_event_btn = gr.Button("Refresh Event Logs", variant="secondary")
            event_list = gr.DataFrame(
                headers=["ID", "Timestamp", "Rule", "Sensor", "Room", "Media", "Status"],
                interactive=False,
            )

            with gr.Row():
                event_id = gr.Number(label="Event Log ID", precision=0)
                event_status = gr.Textbox(label="Event Status", interactive=False)

            with gr.Row():
                with gr.Column(scale=1, variant="panel"):
                    gr.Markdown("Update Event Log")
                    ev_timestamp = gr.Textbox(label="Timestamp (ISO)", placeholder="2026-03-13T12:00:00Z")
                    ev_rule = gr.Textbox(label="Rule Name")
                    ev_sensor = gr.Textbox(label="Sensor ID")
                    ev_room = gr.Textbox(label="Room Name")
                    ev_media = gr.Textbox(label="Media Path")
                    ev_vision = gr.Textbox(label="Vision Response", lines=2)
                    ev_logic = gr.Textbox(label="Logic Response", lines=2)
                    ev_status = gr.Textbox(label="Status")
                    update_event_btn = gr.Button("Update Event Log", variant="primary")
                    delete_event_btn = gr.Button("Delete Event Log", variant="stop")

            refresh_event_btn.click(fn=get_event_logs_df, outputs=event_list)

            def update_event_log(
                e_id, ts, rule, sensor, room, media, vision, logic, status
            ):
                if not e_id:
                    return "Event Log ID required"
                payload = {}
                if ts:
                    payload["timestamp"] = ts
                if rule:
                    payload["rule_name"] = rule
                if sensor:
                    payload["sensor_id"] = sensor
                if room:
                    payload["room_name"] = room
                if media:
                    payload["media_path"] = media
                if vision:
                    payload["vision_response"] = vision
                if logic:
                    payload["logic_response"] = logic
                if status:
                    payload["status"] = status
                try:
                    resp = requests.put(f"{API_URL}/admin/event_logs/{int(e_id)}", json=payload)
                    resp.raise_for_status()
                    return "Event Log Updated"
                except Exception as e:
                    err_msg = str(e)
                    if hasattr(e, "response") and e.response is not None:
                        err_msg += f" - Response: {e.response.text}"
                    return f"Error: {err_msg}"

            update_event_btn.click(
                fn=update_event_log,
                inputs=[
                    event_id,
                    ev_timestamp,
                    ev_rule,
                    ev_sensor,
                    ev_room,
                    ev_media,
                    ev_vision,
                    ev_logic,
                    ev_status,
                ],
                outputs=event_status,
            ).then(fn=get_event_logs_df, outputs=event_list)

            def delete_event_log(e_id):
                if not e_id:
                    return "Event Log ID required"
                try:
                    requests.delete(f"{API_URL}/admin/event_logs/{int(e_id)}").raise_for_status()
                    return "Event Log Deleted"
                except Exception as e:
                    return f"Error: {e}"

            delete_event_btn.click(fn=delete_event_log, inputs=[event_id], outputs=event_status).then(
                fn=get_event_logs_df, outputs=event_list
            )

            event_list.select(fn=_select_int_id, outputs=event_id)

        with gr.Group():
            gr.Markdown("#### Room Occupancy")
            refresh_occupancy_btn = gr.Button("Refresh Room Occupancy", variant="secondary")
            occupancy_list = gr.DataFrame(
                headers=["ID", "Sensor", "Room", "Start", "End", "Active"],
                interactive=False,
            )

            with gr.Row():
                occupancy_id = gr.Number(label="Occupancy ID", precision=0)
                occupancy_status = gr.Textbox(label="Occupancy Status", interactive=False)

            with gr.Row():
                with gr.Column(scale=1, variant="panel"):
                    gr.Markdown("Update Occupancy")
                    oc_sensor = gr.Textbox(label="Sensor ID")
                    oc_room = gr.Textbox(label="Room Name")
                    oc_start = gr.Textbox(label="Start Time (ISO)")
                    oc_end = gr.Textbox(label="End Time (ISO)")
                    oc_active = gr.Dropdown(
                        choices=["", "true", "false"],
                        label="Is Active (optional)",
                        value="",
                    )
                    update_occupancy_btn = gr.Button("Update Occupancy", variant="primary")
                    delete_occupancy_btn = gr.Button("Delete Occupancy", variant="stop")

            refresh_occupancy_btn.click(fn=get_room_occupancy_df, outputs=occupancy_list)

            def update_occupancy(o_id, sensor, room, start, end, active):
                if not o_id:
                    return "Occupancy ID required"
                payload = {}
                if sensor:
                    payload["sensor_id"] = sensor
                if room:
                    payload["room_name"] = room
                if start:
                    payload["start_time"] = start
                if end:
                    payload["end_time"] = end
                active_val = _optional_bool(active)
                if active_val is not None:
                    payload["is_active"] = active_val
                try:
                    resp = requests.put(
                        f"{API_URL}/admin/room_occupancy/{int(o_id)}", json=payload
                    )
                    resp.raise_for_status()
                    return "Occupancy Updated"
                except Exception as e:
                    err_msg = str(e)
                    if hasattr(e, "response") and e.response is not None:
                        err_msg += f" - Response: {e.response.text}"
                    return f"Error: {err_msg}"

            update_occupancy_btn.click(
                fn=update_occupancy,
                inputs=[occupancy_id, oc_sensor, oc_room, oc_start, oc_end, oc_active],
                outputs=occupancy_status,
            ).then(fn=get_room_occupancy_df, outputs=occupancy_list)

            def delete_occupancy(o_id):
                if not o_id:
                    return "Occupancy ID required"
                try:
                    requests.delete(
                        f"{API_URL}/admin/room_occupancy/{int(o_id)}"
                    ).raise_for_status()
                    return "Occupancy Deleted"
                except Exception as e:
                    return f"Error: {e}"

            delete_occupancy_btn.click(
                fn=delete_occupancy, inputs=[occupancy_id], outputs=occupancy_status
            ).then(fn=get_room_occupancy_df, outputs=occupancy_list)

            occupancy_list.select(fn=_select_int_id, outputs=occupancy_id)

        with gr.Group():
            gr.Markdown("#### Emergency Alerts")
            refresh_alerts_btn = gr.Button("Refresh Emergency Alerts", variant="secondary")
            alerts_list = gr.DataFrame(
                headers=[
                    "ID",
                    "Timestamp",
                    "Type",
                    "Description",
                    "Sensor",
                    "Room",
                    "Resolved",
                    "Assistance",
                ],
                interactive=False,
            )

            with gr.Row():
                alert_id = gr.Number(label="Alert ID", precision=0)
                alert_status = gr.Textbox(label="Alert Status", interactive=False)

            with gr.Row():
                with gr.Column(scale=1, variant="panel"):
                    gr.Markdown("Update Alert")
                    al_timestamp = gr.Textbox(label="Timestamp (ISO)")
                    al_type = gr.Textbox(label="Alert Type")
                    al_desc = gr.Textbox(label="Description", lines=2)
                    al_sensor = gr.Textbox(label="Sensor ID")
                    al_room = gr.Textbox(label="Room Name")
                    al_resolved = gr.Dropdown(
                        choices=["", "true", "false"],
                        label="Resolved (optional)",
                        value="",
                    )
                    al_assistance = gr.Dropdown(
                        choices=["", "true", "false"],
                        label="Assistance Needed (optional)",
                        value="",
                    )
                    update_alert_btn = gr.Button("Update Alert", variant="primary")
                    delete_alert_btn = gr.Button("Delete Alert", variant="stop")

            refresh_alerts_btn.click(fn=get_emergency_alerts_df, outputs=alerts_list)

            def update_alert(a_id, ts, a_type, desc, sensor, room, resolved, assist):
                if not a_id:
                    return "Alert ID required"
                payload = {}
                if ts:
                    payload["timestamp"] = ts
                if a_type:
                    payload["alert_type"] = a_type
                if desc:
                    payload["description"] = desc
                if sensor:
                    payload["sensor_id"] = sensor
                if room:
                    payload["room_name"] = room
                resolved_val = _optional_bool(resolved)
                if resolved_val is not None:
                    payload["resolved"] = resolved_val
                assist_val = _optional_bool(assist)
                if assist_val is not None:
                    payload["assistance_needed"] = assist_val
                try:
                    resp = requests.put(
                        f"{API_URL}/admin/emergency_alerts/{int(a_id)}", json=payload
                    )
                    resp.raise_for_status()
                    return "Alert Updated"
                except Exception as e:
                    err_msg = str(e)
                    if hasattr(e, "response") and e.response is not None:
                        err_msg += f" - Response: {e.response.text}"
                    return f"Error: {err_msg}"

            update_alert_btn.click(
                fn=update_alert,
                inputs=[
                    alert_id,
                    al_timestamp,
                    al_type,
                    al_desc,
                    al_sensor,
                    al_room,
                    al_resolved,
                    al_assistance,
                ],
                outputs=alert_status,
            ).then(fn=get_emergency_alerts_df, outputs=alerts_list)

            def delete_alert(a_id):
                if not a_id:
                    return "Alert ID required"
                try:
                    requests.delete(
                        f"{API_URL}/admin/emergency_alerts/{int(a_id)}"
                    ).raise_for_status()
                    return "Alert Deleted"
                except Exception as e:
                    return f"Error: {e}"

            delete_alert_btn.click(fn=delete_alert, inputs=[alert_id], outputs=alert_status).then(
                fn=get_emergency_alerts_df, outputs=alerts_list
            )

            alerts_list.select(fn=_select_int_id, outputs=alert_id)

        with gr.Group():
            gr.Markdown("#### Active Image State")
            refresh_state_btn = gr.Button("Refresh Active Image State", variant="secondary")
            state_list = gr.DataFrame(headers=["ID", "Expires At"], interactive=False)

            with gr.Row():
                state_id = gr.Number(label="State ID", precision=0)
                state_status = gr.Textbox(label="State Status", interactive=False)

            with gr.Row():
                with gr.Column(scale=1, variant="panel"):
                    gr.Markdown("Update State")
                    state_expires = gr.Textbox(label="Expires At (ISO)")
                    update_state_btn = gr.Button("Update State", variant="primary")
                    delete_state_btn = gr.Button("Delete State", variant="stop")

            refresh_state_btn.click(fn=get_active_image_state_df, outputs=state_list)

            def update_state(s_id, expires_at):
                if not s_id:
                    return "State ID required"
                payload = {}
                if expires_at:
                    payload["expires_at"] = expires_at
                try:
                    resp = requests.put(
                        f"{API_URL}/admin/active_image_state/{int(s_id)}", json=payload
                    )
                    resp.raise_for_status()
                    return "State Updated"
                except Exception as e:
                    err_msg = str(e)
                    if hasattr(e, "response") and e.response is not None:
                        err_msg += f" - Response: {e.response.text}"
                    return f"Error: {err_msg}"

            update_state_btn.click(
                fn=update_state, inputs=[state_id, state_expires], outputs=state_status
            ).then(fn=get_active_image_state_df, outputs=state_list)

            def delete_state(s_id):
                if not s_id:
                    return "State ID required"
                try:
                    requests.delete(
                        f"{API_URL}/admin/active_image_state/{int(s_id)}"
                    ).raise_for_status()
                    return "State Deleted"
                except Exception as e:
                    return f"Error: {e}"

            delete_state_btn.click(fn=delete_state, inputs=[state_id], outputs=state_status).then(
                fn=get_active_image_state_df, outputs=state_list
            )

            state_list.select(fn=_select_int_id, outputs=state_id)

# --- Application Startup ---
_primary = gr.themes.Color(
    c50="#F0EEFF",    # near-white lavender — light mode bg tint
    c100="#D9D4FF",   # soft violet
    c200="#B8AFFF",   # bright light purple — dark mode accent base
    c300="#9489F5",   # vivid medium purple — dark mode button text/borders
    c400="#7060E0",   # bold purple — dark mode primary interactive
    c500="#4D3BB8",   # deep purple — light mode hover
    c600="#36278F",   # dark purple — light mode primary button
    c700="#1B192E",   # brand anchor (#1B192E)
    c800="#130F24",   # deeper navy
    c900="#0B0919",
    c950="#05040D",
)

with gr.Blocks(theme=gr.themes.Soft(primary_hue=_primary)) as console:
    gr.Markdown("# Cognitive Companion Console")
    create_rules_tab()
    create_sensors_tab()
    create_admin_tab()
    create_vision_tab()
    create_translation_tab()

    console.load(fn=get_rules_df, outputs=None) # Note: can't easily auto-populate gr.DataFrame on load cleanly without state vars, skipping auto-load for simplicity

if __name__ == "__main__":
    console.launch(server_name="0.0.0.0", server_port=7860)
