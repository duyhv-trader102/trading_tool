from typing import Dict, List, Optional

TPO_COLORS = [
    '#FFFFFF',  # A — white (IB start)
    '#E0E0FF',  # B — bright lavender (IB end)
    '#A8E06C',  # C — lime
    '#F0D04A',  # D — gold
    '#F0943A',  # E — orange
    '#EF5A5A',  # F — coral red (latest)
]

def label_color(label: str, n_periods: int = 6) -> str:
    """Get time-gradient color for TPO label."""
    if label == 'O': return '#00FFFF'
    if label == '#': return '#FF00FF'
    if label.isupper(): idx = ord(label) - ord('A')
    elif label.islower(): idx = ord(label) - ord('a') + 26
    else: idx = int(label) if label.isdigit() else 0
    return TPO_COLORS[idx % len(TPO_COLORS)]

def sort_labels(labels) -> List[str]:
    """Sort: O first, A-Z, a-z, numbers, # last."""
    def key(l):
        if l == 'O': return (0, 0)
        if l == '#': return (4, 0)
        if l.isupper(): return (1, ord(l))
        if l.islower(): return (2, ord(l))
        return (3, int(l) if l.isdigit() else 999)
    return sorted(labels, key=key)

def get_last_label(profile: dict) -> Optional[str]:
    """Find last regular label (excluding O and #)."""
    labels = set()
    for v in profile.values(): labels.update(v)
    regular = [l for l in labels if l not in ('O', '#')]
    return sort_labels(regular)[-1] if regular else None

def filter_labels(labels: set, last_label: Optional[str]) -> set:
    """Remove duplicate markers."""
    result = set(labels)
    if 'O' in result and 'A' in result: result.discard('A')
    if '#' in result and last_label and last_label in result: result.discard(last_label)
    return result

def aggregate_profile(profile: Dict[float, List[str]], block_size: float) -> Dict[float, List[str]]:
    """Aggregate profile into blocks."""
    last_label = get_last_label(profile)
    blocks = {}
    for price, labels in profile.items():
        block = round(price / block_size) * block_size
        if block not in blocks: blocks[block] = set()
        blocks[block].update(labels)
    return {k: sort_labels(filter_labels(v, last_label)) for k, v in blocks.items()}
