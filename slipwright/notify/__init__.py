"""Notifications: telling people in Telegram, Slack, Discord and Teams that an agent is
waiting, and letting whoever may decide it say "carry on" or "reject, because…" from
there.

``core`` decides -- see its docstring for the three rules it rests on; the channel
modules (``telegram``, ``slack``, ``discord``, ``msteams``) speak each service's
protocol; ``listeners`` runs the bots that hear the presses. Nothing is imported here on
purpose: the store reads ``models`` and must not pull the notifier in with it.
"""
