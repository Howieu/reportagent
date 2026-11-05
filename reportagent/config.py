"""语义配置：描述数仓里的表和字段，产品其余部分只认这里的逻辑名。"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

IDENT = re.compile(r"^[A-Za-z_][\w$]*$")
TABLE = re.compile(r"^[A-Za-z_][\w$]*(\.[A-Za-z_][\w$]*)*$")

REQUIRED = {
    "sales": {"table", "date", "store", "channel", "category", "subcategory", "family", "item",
              "sales", "qty", "ticket"},
    "goals": {"table", "date", "store", "category", "channel", "sales_goal"},
    "traffic": {"table", "date", "store", "channel", "visitors"},
    "items": {"table", "item"},
    "stores": {"table", "store"},
    "availability": {"table", "date", "store", "item", "available_pct"},
    "funnel": {"table", "date", "user", "event", "steps", "dimensions"},
}
OPTIONAL = {
    "sales": {"subchannel"},
    "traffic": {"category"},
    "items": {"name", "image_url", "exclude_flag", "segments"},
    "stores": {"name", "peer_group", "region", "city"},
    "funnel": {"note"},
}
DEFAULT_LABELS = {
    "store": "门店", "category": "品类", "subcategory": "子类", "family": "品牌", "item": "SKU",
    "channel": "渠道", "subchannel": "二级渠道", "region": "区域", "city": "城市",
}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Source:
    table: str
    columns: dict
    segments: dict = field(default_factory=dict)
    steps: tuple = ()
    dimensions: dict = field(default_factory=dict)
    note: str = ""

    def col(self, name):
        return self.columns[name]

    def has(self, name):
        return name in self.columns


@dataclass(frozen=True)
class Semantic:
    name: str
    sources: dict
    labels: dict
    fiscal_year_start_month: int = 1
    ly_shift_days: int = 364
    date_format: str | None = None
    default_channel: str = ""
    default_focus: str = "sales"
    glossary: tuple = ()
    constraints: tuple = ()
    banned_phrases: tuple = ()
    verified_questions: tuple = ()
    synonyms: dict = field(default_factory=dict)
    branding: dict = field(default_factory=dict)
    synthetic: bool = False
    currency: str = "¥"
    data_note: str = ""
    examples: tuple = ()

    def has(self, source):
        return source in self.sources

    def source(self, name):
        return self.sources[name]


def _source(name, raw):
    if name not in REQUIRED:
        raise ConfigError(f"未知数据源: {name}")
    raw = dict(raw or {})
    missing = REQUIRED[name] - raw.keys()
    if missing:
        raise ConfigError(f"sources.{name} 缺少: {', '.join(sorted(missing))}")
    unknown = raw.keys() - REQUIRED[name] - OPTIONAL.get(name, set())
    if unknown:
        raise ConfigError(f"sources.{name} 有未知字段: {', '.join(sorted(unknown))}")
    table = raw.pop("table")
    if not TABLE.match(str(table)):
        raise ConfigError(f"非法表名: {table}")
    segments = raw.pop("segments", {}) or {}
    steps = tuple(raw.pop("steps", ()) or ())
    dimensions = dict(raw.pop("dimensions", {}) or {})
    note = str(raw.pop("note", "") or "")
    raw.update({column: column for column in dimensions})
    for col in [*raw.values(), *segments.values()]:
        if not IDENT.match(str(col)):
            raise ConfigError(f"非法字段名: {col}")
    return Source(table=table, columns=raw, segments=segments, steps=steps, dimensions=dimensions, note=note)


def load_semantic(path) -> Semantic:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    sources = {k: _source(k, v) for k, v in (raw.get("sources") or {}).items()}
    if "sales" not in sources:
        raise ConfigError("sources.sales 必填")
    cal = raw.get("calendar") or {}
    month = int(cal.get("fiscal_year_start_month", 1))
    if not 1 <= month <= 12:
        raise ConfigError("fiscal_year_start_month 需在 1-12")
    defaults = raw.get("defaults") or {}
    focus = defaults.get("focus", "sales")
    if focus not in {"sales", "qty"}:
        raise ConfigError("defaults.focus 仅支持 sales 或 qty")
    return Semantic(
        name=raw.get("name", "零售数仓"),
        sources=sources,
        labels={**DEFAULT_LABELS, **(raw.get("labels") or {})},
        fiscal_year_start_month=month,
        ly_shift_days=int(cal.get("ly_shift_days", 364)),
        date_format=cal.get("date_format"),
        default_channel=str(defaults.get("channel", "")),
        default_focus=focus,
        glossary=tuple(raw.get("glossary") or ()),
        constraints=tuple(raw.get("constraints") or ()),
        banned_phrases=tuple(raw.get("banned_phrases") or ()),
        verified_questions=tuple(raw.get("verified_questions") or ()),
        branding=dict(raw.get("branding") or {}),
        synthetic=bool(raw.get("synthetic", False)),
        currency=str(raw.get("currency", "¥")),
        data_note=str(raw.get("data_note", "")),
        examples=tuple(raw.get("examples") or ()),
        synonyms={str(k): str(v) for k, v in (raw.get("synonyms") or {}).items()},
    )


def load_env(path=".env"):
    """读取 .env，已存在的环境变量优先。"""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'\""))
