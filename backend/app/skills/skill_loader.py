from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple


@dataclass
class SkillDoc:
    name: str
    description: str
    tags: List[str]
    body: str


class NavigationSkillLoader:
    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = skills_dir
        self.skills: Dict[str, SkillDoc] = {}
        self._load()

    def _parse_frontmatter(self, text: str) -> Tuple[Dict[str, str], str]:
        if not text.startswith("---"):
            return {}, text
        parts = text.split("---", 2)
        if len(parts) < 3:
            return {}, text
        raw_meta, body = parts[1], parts[2].strip()
        meta: Dict[str, str] = {}
        for line in raw_meta.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip()
        return meta, body

    def _load(self) -> None:
        self.skills.clear()
        if not self.skills_dir.exists():
            return
        for skill_file in sorted(self.skills_dir.rglob("SKILL.md")):
            text = skill_file.read_text(encoding="utf-8")
            meta, body = self._parse_frontmatter(text)
            name = meta.get("name") or skill_file.parent.name
            desc = meta.get("description", "")
            tags = [item.strip() for item in meta.get("tags", "").split(",") if item.strip()]
            self.skills[name] = SkillDoc(name=name, description=desc, tags=tags, body=body)

    def list_descriptions(self) -> List[Dict[str, str]]:
        return [
            {"name": skill.name, "description": skill.description, "tags": ", ".join(skill.tags)}
            for skill in self.skills.values()
        ]

    def default_skills(self) -> List[str]:
        return ["balanced_navigation"] if "balanced_navigation" in self.skills else list(self.skills)[:1]

    def match(self, goal: str) -> List[str]:
        goal_text = (goal or "").lower()
        hits: List[str] = []
        patterns = {
            "urban_canyon": [r"城市峡谷", r"urban", r"遮挡", r"连续性", r"跳变"],
            "open_precision": [r"开阔", r"精度", r"precision", r"高精"],
            "occlusion_recovery": [r"遮挡", r"高楼", r"恢复", r"recovery", r"高风险"],
            "dynamic_robust": [r"动态", r"稳健", r"robust", r"载体", r"机动"],
            "balanced_navigation": [r"平衡", r"综合", r"通用", r"默认", r"balanced"],
        }
        for name, regs in patterns.items():
            if name not in self.skills:
                continue
            if any(re.search(reg, goal_text, flags=re.IGNORECASE) for reg in regs):
                hits.append(name)
        if not hits:
            hits = self.default_skills()
        if "balanced_navigation" in self.skills and "balanced_navigation" not in hits:
            hits.append("balanced_navigation")
        return hits[:3]

    def get_payload(self, names: List[str]) -> Dict[str, object]:
        docs = []
        for name in names:
            skill = self.skills.get(name)
            if not skill:
                continue
            excerpt = "\n".join(skill.body.splitlines()[:8]).strip()
            docs.append(
                {
                    "name": skill.name,
                    "description": skill.description,
                    "tags": skill.tags,
                    "excerpt": excerpt,
                    "body": skill.body,
                }
            )
        return {"skills": docs, "skill_names": [doc["name"] for doc in docs]}
