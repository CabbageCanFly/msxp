"""Bounded in-memory identity suggestions and diagnostic verification reasons only."""

from collections import deque
from dataclasses import asdict
from datetime import datetime
import hashlib
import math
import time

from exp_tracker.diagnostic_evidence import CONFIRM_GAP_SECONDS, WRAP_FROM_BP, WRAP_TO_BP
from exp_tracker.exp_consistency import MODES, assess, displayed_bp
from exp_tracker.models import Reading
from exp_tracker.validation import Observation, validate_transition
from character_name_ocr import name_region, name_text


class IdentitySuggestions:
    """One instance per channel. An established proposal is NEVER silently replaced."""

    def __init__(self, channel):
        self.channel = channel
        self.proposed = None
        self.proposed_evidence = []
        self.pending_switch = None
        self.streak = []
        self.seen = deque(maxlen=128)
        self.last_at = None

    def observe(self, evidence):
        when = datetime.fromisoformat(evidence['received_at'])
        reason = evidence['status']
        if self.last_at and when <= self.last_at:
            reason = 'out_of_order'
        elif evidence['pixel_sha256'] and evidence['pixel_sha256'] in self.seen:
            reason = 'duplicate_frame'
        else:
            if self.last_at and (when - self.last_at).total_seconds() > CONFIRM_GAP_SECONDS:
                self.streak = []
            self.last_at = when
            if evidence['pixel_sha256']:
                self.seen.append(evidence['pixel_sha256'])
            if evidence['status'] != 'candidate':
                self.streak = []
            else:
                name = evidence['name']
                if self.streak and self.streak[-1]['name'] != name:
                    self.streak = []
                reference = {k: evidence[k] for k in ('name', 'pixel_sha256', 'received_at', 'box', 'score')}
                self.streak = (self.streak + [reference])[-2:]
                if len(self.streak) == 2:
                    if self.proposed is None:
                        self.proposed, self.proposed_evidence = name, list(self.streak)
                    elif name != self.proposed:
                        self.pending_switch = dict(kind='possible_character_switch',name=name,
                                                   evidence=list(self.streak),review_required=True)
                    else:
                        self.proposed_evidence = list(self.streak)
        return dict(channel=self.channel, proposed_name=self.proposed,
                    proposed_evidence=self.proposed_evidence, pending_switch=self.pending_switch,
                    confirming_name=self.streak[-1]['name'] if self.streak else None,
                    confirming_frames=len(self.streak), latest_status=reason, trusted=False,
                    review_required=bool(self.proposed or self.pending_switch))


class IdentityCapture:
    def __init__(self, channel, *, interval=0):
        self.suggestions = IdentitySuggestions(channel)
        self.interval = interval
        self.last_check = None
        self.previous = None

    def numeric_check(self, result, received_at, requirements):
        """Use the existing transition validator and both existing rounding hypotheses."""
        pair, level = result.get('candidate'), result.get('visual_level')
        if not result.get('current') or pair is None or level is None:
            return dict(check_now=bool(result.get('current') and (self.previous or self.suggestions.proposed)),
                        reason='numeric_unavailable', classification='unknown')
        checks = {mode: assess(level, pair[0], pair[1], requirements, mode) for mode in MODES}
        if all(c['status'] == 'inconsistent' for c in checks.values()):
            return dict(check_now=True, reason='contradicts_both_display_hypotheses',
                        classification='possible_bad_ocr', arithmetic=checks)
        current = Observation(self.suggestions.channel, datetime.fromisoformat(received_at), Reading(level, *pair))
        before = self.previous
        transition = validate_transition(before, current, max_gap_seconds=CONFIRM_GAP_SECONDS)
        classification = transition.reason
        if before and transition.reason == 'level_change_requires_confirmation':
            seconds = (current.captured_at - before.captured_at).total_seconds()
            a, b = before.reading, current.reading
            if b.level < a.level:
                classification = 'level_decrease'
            elif seconds > CONFIRM_GAP_SECONDS:
                classification = 'possible_offstream_progression'
            elif (b.level == a.level + 1 and displayed_bp(a.percentage) >= WRAP_FROM_BP
                  and displayed_bp(b.percentage) < WRAP_TO_BP):
                classification = 'possible_normal_level_up'
        # Do not let a suspect sample replace the numerical comparison anchor.
        if transition.status in ('accepted', 'baseline'):
            self.previous = current
        return dict(check_now=transition.status in ('ambiguous', 'rejected'),
                    reason=transition.reason, classification=classification,
                    transition=asdict(transition), arithmetic=checks)

    def inspect(self, result, frame, image, layouts, read_name, requirements, *, max_age, clock=time.monotonic):
        started = clock()
        digest = hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest() if image else None
        evidence = dict(status='unavailable', name=None, score=None, raw=None, box=None,
                        received_at=frame.received_at, pixel_sha256=digest,
                        frame_sha256=hashlib.sha256(frame.png).hexdigest(), trusted=False,
                        provenance=dict(field='own_name_status_panel', layout_count=len(layouts),
                                        frame_sequence=frame.sequence, owner_verified=False))
        numeric = self.numeric_check(result, frame.received_at, requirements)
        needs_confirmation = self.suggestions.proposed is None or bool(self.suggestions.streak and
            self.suggestions.streak[-1]['name'] != self.suggestions.proposed)
        due = (self.last_check is None or started - self.last_check >= self.interval
               or numeric['check_now'] or needs_confirmation)
        evidence['verification_reason'] = ('numeric_event' if numeric['check_now'] else
                                           'confirmation' if needs_confirmation else 'periodic')
        if len(layouts) > 1:
            evidence['status'] = 'multiple_huds'
        elif not result.get('current') or image is None or not layouts:
            evidence['status'] = 'ineligible_frame'
        elif not due:
            evidence['status'] = 'not_due'
        else:
            self.last_check = started
            try:
                region = name_region(layouts[0], image.size)
                evidence['box'] = region['box']
                evidence['provenance'].update(search=layouts[0].get('search', 'full_frame'),
                    full_frame_age_seconds=layouts[0].get('full_frame_age_seconds', 0))
                response = read_name(image.crop(region['box']))
                evidence['raw'] = response
                texts, scores = (response.get('raw') or {}).get('txts'), (response.get('raw') or {}).get('scores')
                valid = (isinstance(texts, list) and len(texts) == 1 and isinstance(texts[0], str)
                         and len(texts[0]) <= 160 and isinstance(scores, list) and len(scores) == 1
                         and type(scores[0]) in (int, float) and math.isfinite(scores[0]) and 0 <= scores[0] <= 1)
                if valid:
                    evidence['score'] = scores[0]
                    evidence['name'] = name_text(texts[0]) if scores[0] >= .5 else None
                evidence['status'] = 'candidate' if evidence['name'] else 'unreadable_or_conflicting'
            except (OSError, RuntimeError, ValueError, KeyError) as error:
                evidence.update(status='failed', error=type(error).__name__)
        if clock() - frame.arrived_monotonic > max_age:
            evidence.update(status='stale_local_frame', name=None)
        evidence['seconds'] = clock() - started
        if evidence['status'] == 'not_due':
            # Skipping work must not manufacture another vote or break a real confirmation.
            suggestion = dict(channel=self.suggestions.channel, proposed_name=self.suggestions.proposed,
                proposed_evidence=self.suggestions.proposed_evidence, pending_switch=self.suggestions.pending_switch,
                latest_status='not_due', trusted=False, review_required=bool(self.suggestions.proposed))
        else:
            suggestion = self.suggestions.observe(evidence)
        mismatch = bool(evidence['name'] and suggestion['proposed_name']
                        and evidence['name'] != suggestion['proposed_name'])
        return dict(evidence=evidence, suggestion=suggestion, numeric_check=numeric,
                    suspect_reading_hold_recommended=bool(numeric['check_now'] or mismatch
                                                         or suggestion.get('pending_switch')),
                    tracking_action='none')

    def missing(self, received_at):
        return self.suggestions.observe(dict(status='capture_failed', received_at=received_at, pixel_sha256=None))
