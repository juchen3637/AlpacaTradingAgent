"""webui/components/plays_page.py - 'Plays' page (multi-view of saved plays).

Lists all SAVED_PLAYS entries as a responsive 2-col card grid. Each card
shows the original playbook levels, the current price + position state, and
a colored verdict badge. Per-card actions: Re-analyze, Open in Scanner,
Exit Now (if position open), Cancel Pending (if order unfilled), Delete.
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html


def _section_header(icon: str, title: str, subtitle: str = ""):
    return html.Div(
        [
            html.Div(
                [
                    html.Span(
                        icon, className="material-symbols-outlined",
                        style={"color": "#3B82F6", "fontSize": "20px"},
                    ),
                    html.Span(
                        title,
                        style={"fontFamily": "'Space Grotesk', sans-serif",
                               "fontWeight": "700", "fontSize": "14px",
                               "letterSpacing": "1px", "marginLeft": "8px"},
                    ),
                ],
                style={"display": "flex", "alignItems": "center"},
            ),
            html.Div(subtitle, style={"fontSize": "12px", "color": "#94A3B8",
                                      "marginTop": "4px"}) if subtitle else None,
        ],
        style={"marginBottom": "16px"},
    )


def _filter_bar():
    label_style = {"fontSize": "11px", "color": "#94A3B8",
                   "textTransform": "uppercase", "letterSpacing": "1px"}
    return dbc.Card(
        dbc.CardBody(
            [
                _section_header(
                    "tune", "FILTER & SORT",
                    "All saved plays. Filter by status / strategy / symbol; sort by recency.",
                ),
                dbc.Row(
                    [
                        dbc.Col([
                            html.Label("Symbol", style=label_style),
                            dbc.Input(id="plays-filter-symbol", type="text",
                                      placeholder="e.g. NVDA", value=""),
                        ], xs=12, md=3),
                        dbc.Col([
                            html.Label("Status", style=label_style),
                            dcc.Dropdown(
                                id="plays-filter-status",
                                options=[
                                    {"label": "All", "value": "all"},
                                    {"label": "Has open position", "value": "has_position"},
                                    {"label": "Pending order", "value": "pending"},
                                    {"label": "No position / closed", "value": "none"},
                                    {"label": "Unanalyzed", "value": "unanalyzed"},
                                ],
                                value="all", clearable=False,
                            ),
                        ], xs=12, md=3),
                        dbc.Col([
                            html.Label("Verdict", style=label_style),
                            dcc.Dropdown(
                                id="plays-filter-verdict",
                                options=[
                                    {"label": "Any", "value": "any"},
                                    {"label": "Still viable", "value": "still_viable"},
                                    {"label": "Degraded", "value": "degraded"},
                                    {"label": "Invalidated", "value": "invalidated"},
                                    {"label": "Played out", "value": "thesis_played_out"},
                                ],
                                value="any", clearable=False,
                            ),
                        ], xs=12, md=3),
                        dbc.Col([
                            html.Label("Sort", style=label_style),
                            dcc.Dropdown(
                                id="plays-sort",
                                options=[
                                    {"label": "Last opened (newest)", "value": "last_opened_desc"},
                                    {"label": "Created (newest)", "value": "created_desc"},
                                    {"label": "Created (oldest)", "value": "created_asc"},
                                    {"label": "Symbol A→Z", "value": "symbol_asc"},
                                ],
                                value="last_opened_desc", clearable=False,
                            ),
                        ], xs=12, md=3),
                    ],
                ),
            ],
            style={"padding": "20px"},
        ),
        className="glass-card mb-3",
    )


def _grid_wrapper():
    """Empty grid container — populated by render_plays_grid callback."""
    return html.Div(
        id="plays-grid",
        children=html.Div(
            "Loading saved plays…",
            style={"color": "#64748B", "fontStyle": "italic",
                   "padding": "30px", "textAlign": "center"},
        ),
    )


def _exit_confirm_modal():
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Exit Position"), close_button=True),
            dbc.ModalBody(id="plays-exit-body", style={"color": "#F1F5F9"}),
            dbc.ModalFooter([
                dbc.Button("Keep Position", id="plays-exit-cancel-btn",
                           color="secondary", outline=True),
                dbc.Button("Exit Now", id="plays-exit-confirm-btn",
                           color="danger"),
            ]),
        ],
        id="plays-exit-modal",
        is_open=False, size="md", centered=True, backdrop="static",
    )


def _cancel_order_confirm_modal():
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Cancel Pending Order"), close_button=True),
            dbc.ModalBody(id="plays-cancel-order-body", style={"color": "#F1F5F9"}),
            dbc.ModalFooter([
                dbc.Button("Keep Order", id="plays-cancel-order-cancel-btn",
                           color="secondary", outline=True),
                dbc.Button("Confirm & Cancel", id="plays-cancel-order-confirm-btn",
                           color="warning"),
            ]),
        ],
        id="plays-cancel-order-modal",
        is_open=False, size="md", centered=True, backdrop="static",
    )


def _execute_confirm_modal():
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Confirm Paper Trade"), close_button=True),
            dbc.ModalBody(id="plays-execute-body", style={"color": "#F1F5F9"}),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="plays-execute-cancel-btn",
                           color="secondary", outline=True),
                dbc.Button("Confirm & Submit", id="plays-execute-confirm-btn",
                           color="success"),
            ]),
        ],
        id="plays-execute-modal",
        is_open=False, size="md", centered=True, backdrop="static",
    )


def _delete_confirm_modal():
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Delete Saved Play"), close_button=True),
            dbc.ModalBody(id="plays-delete-body", style={"color": "#F1F5F9"}),
            dbc.ModalFooter([
                dbc.Button("Cancel", id="plays-delete-cancel-btn",
                           color="secondary", outline=True),
                dbc.Button("Delete", id="plays-delete-confirm-btn",
                           color="danger"),
            ]),
        ],
        id="plays-delete-modal",
        is_open=False, size="sm", centered=True, backdrop="static",
    )


def create_plays_page():
    """Assemble the full Plays page layout."""
    return html.Div(
        [
            # Stores: which play_id is the user about to act on?
            dcc.Store(id="plays-tick", data=0),
            dcc.Store(id="plays-pending-action"),
            dcc.Store(id="plays-pending-delete-id"),
            dcc.Store(id="plays-pending-exit-id"),
            dcc.Store(id="plays-pending-cancel-id"),
            dcc.Store(id="plays-pending-execute"),
            html.Div(id="plays-status",
                     style={"fontSize": "13px", "marginBottom": "8px"}),
            _filter_bar(),
            _grid_wrapper(),
            _exit_confirm_modal(),
            _cancel_order_confirm_modal(),
            _execute_confirm_modal(),
            _delete_confirm_modal(),
        ]
    )
