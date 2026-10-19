"""persona.py — builds the voice agent's system prompt from config/business.yaml.

The business facts live in YAML so a non-developer can edit them.
This module turns them into the prompt the LLM speaks from.
"""
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "business.yaml"


def load_business(path=CONFIG_PATH):
    with open(path) as f:
        return yaml.safe_load(f)


def build_system_prompt(b):
    biz = b["business"]
    agent = b["agent"]
    lines = [
        f"You are {agent['role']} for {biz['name']} ({biz['short_name']}), "
        f"a forklift dealership at {biz['address']}, phone {biz['phone']}.",
        "",
        "SHOP HOURS: " + biz["hours"] + ". You are answering because the shop "
        "is currently closed or unavailable.",
        "",
        "SERVICES: " + "; ".join(b["services"]) + ".",
        "",
        "YOUR JOB: take the caller's information so the team can call back "
        "first thing in the morning. Collect, in order:",
    ]
    for field in b["intake"]["fields"]:
        lines.append(f"  - {field}")
    lines += [
        "",
        "Read the callback number back digit by digit and get explicit "
        "confirmation before ending the call.",
        "",
        "URGENCY: if the caller's equipment is down right now or anyone could "
        "get hurt, say you are flagging it as urgent.",
        "",
        "RULES:",
    ]
    for rule in b["rules"]:
        lines.append(f"  - {rule}")
    lines += [
        "",
        "When you have the name and a confirmed callback number, call the "
        "record_lead function with everything you collected, then say the "
        "closing line and end the call.",
        "",
        "CLOSING LINE: " + b["intake"]["closing_line"].strip(),
        "",
        "GREETING (say this first, exactly once):",
        agent["greeting"].strip(),
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(build_system_prompt(load_business()))
