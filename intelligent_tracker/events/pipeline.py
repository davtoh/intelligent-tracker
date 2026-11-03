"""Pipeline orchestration factory for initializing EventBus, dispatchers, and alert rules."""

from typing import Any, Dict, Optional

from intelligent_tracker.events.bus import EventBus
from intelligent_tracker.events.mqtt import MqttPublisher
from intelligent_tracker.events.rules import AlertRule, AlertRuleEngine, QuietHours
from intelligent_tracker.events.telegram import TelegramDispatcher
from intelligent_tracker.events.webhooks import WebhookDispatcher


def setup_event_pipeline(
    config: Dict[str, Any],
    event_bus: Optional[EventBus] = None,
) -> Dict[str, Any]:
    """
    Parse configuration dictionary and initialize event bus, dispatchers, and rules.

    :param config: Dictionary loaded from YAML (e.g. `configs/alert_demo.yaml`).
    :param event_bus: Optional existing EventBus instance.
    :return: Dictionary containing initialized components.
    """
    bus = event_bus or EventBus()
    alert_cfg = config.get("alerting", config.get("events", {}))

    dispatchers: Dict[str, Any] = {
        "event_bus": bus,
        "webhooks": [],
        "telegram": None,
        "mqtt": None,
        "rule_engine": None,
    }

    # 1. Setup Webhooks
    for wh in alert_cfg.get("webhooks", []):
        url = wh.get("url")
        if url:
            dispatcher = WebhookDispatcher(
                url=url,
                auth_header=wh.get("auth_header") or wh.get("auth_token"),
                timeout=wh.get("timeout", 5.0),
                max_retries=wh.get("max_retries", 3),
                backoff_factor=wh.get("backoff_factor", 0.5),
                include_snapshot=wh.get("include_snapshot", True),
                event_types=wh.get("event_types"),
                headers=wh.get("headers"),
            )
            bus.subscribe(dispatcher.send)
            dispatchers["webhooks"].append(dispatcher)

    # 2. Setup Telegram Bot
    tg_cfg = alert_cfg.get("telegram")
    if tg_cfg and tg_cfg.get("enabled", True):
        tg = TelegramDispatcher(
            token=tg_cfg.get("token"),
            chat_id=tg_cfg.get("chat_id"),
            cooldown=tg_cfg.get("cooldown", 60.0),
            include_snapshot=tg_cfg.get("include_snapshot", True),
            mock=tg_cfg.get("mock", False),
        )
        bus.subscribe(tg.send)
        dispatchers["telegram"] = tg

    # 3. Setup MQTT Publisher
    mqtt_cfg = alert_cfg.get("mqtt")
    if mqtt_cfg and mqtt_cfg.get("enabled", True):
        mqtt_pub = MqttPublisher(
            broker=mqtt_cfg.get("broker", "localhost"),
            port=mqtt_cfg.get("port", 1883),
            username=mqtt_cfg.get("username"),
            password=mqtt_cfg.get("password"),
            client_id=mqtt_cfg.get("client_id", "intelligent_tracker"),
            base_topic=mqtt_cfg.get("base_topic", "tracker"),
            qos=mqtt_cfg.get("qos", 1),
            retain_occupancy=mqtt_cfg.get("retain_occupancy", True),
            retain_sightings=mqtt_cfg.get("retain_sightings", True),
            mock=mqtt_cfg.get("mock", False),
        )
        mqtt_pub.connect()
        bus.subscribe(mqtt_pub.send)
        dispatchers["mqtt"] = mqtt_pub

    # 4. Setup Alert Rules
    rules_cfg = alert_cfg.get("rules", [])
    if rules_cfg:
        rule_objs = []
        for r in rules_cfg:
            qh = None
            qh_cfg = r.get("quiet_hours")
            if qh_cfg:
                qh = QuietHours(
                    start_time=qh_cfg.get("start", "22:00"),
                    end_time=qh_cfg.get("end", "06:00"),
                    days=qh_cfg.get("days"),
                )

            rule_objs.append(
                AlertRule(
                    name=r.get("name", "unnamed_rule"),
                    zone_id=r.get("zone_id"),
                    event_types=r.get("event_types"),
                    categories=r.get("categories"),
                    min_dwell_time=r.get("min_dwell_time"),
                    quiet_hours_only=r.get("quiet_hours_only", False) or (qh is not None),
                    quiet_hours=qh,
                    cooldown=r.get("cooldown", 60.0),
                    severity=r.get("severity", "critical"),
                    message_template=r.get("message"),
                    actions=r.get("actions", ["webhook", "telegram", "mqtt"]),
                )
            )

        rule_engine = AlertRuleEngine(rules=rule_objs, event_bus=bus)
        bus.subscribe(lambda ev: rule_engine.evaluate(ev))
        dispatchers["rule_engine"] = rule_engine

    # Start event bus async workers
    bus.start()
    return dispatchers

