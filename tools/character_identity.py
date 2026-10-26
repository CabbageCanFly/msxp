"""Bounded in-memory identity suggestions and diagnostic verification reasons only."""

from collections import deque
from dataclasses import asdict
from datetime import datetime
import hashlib
import math
import time

from exp_tracker.diagnostic_evidence import CONFIRM_GAP_SECONDS, WRAP_FROM_BP, WRAP_TO_BP
from exp_tracker.exp_consistency import MODES, assess, displayed_bp
from exp_tracker.jobs import match, next_level, tier
from exp_tracker.models import Reading, same_character_name
from exp_tracker.validation import Observation, validate_transition
from character_name_ocr import clean_name_crop, job_region, name_region, name_text, second_look


# Numeric changes another character could explain; the rest stay ordinary EXP-validity questions.
OWNERSHIP_RISK = {'reset_loss_or_character_switch', 'level_decrease',
                  'level_change_requires_confirmation', 'possible_offstream_progression'}
PENDING_TTL_SECONDS = 600
JOB_RETRY_SECONDS = 60  # Until two job reads agree, or after one disagreed with the known job.
JOB_RECHECK_SECONDS = 600  # Once the level allows the next job advancement.


class IdentitySuggestions:
    """One instance per channel. Only select() records a committed identity and its source."""

    def __init__(self, channel, *, confirmed=None, pending_ttl=PENDING_TTL_SECONDS, confirmation_source='operator_confirmed'):
        self.channel = channel
        self.confirmed = confirmed
        self.confirmation_source = confirmation_source
        self.pending_ttl = pending_ttl
        self.proposed = None
        self.proposed_evidence = []
        self.pending_switch = None
        self.history = deque(maxlen=16)
        self.streak = []
        self.seen = deque(maxlen=128)
        self.last_at = None
        self.reference_seen_at = None

    @property
    def reference(self):
        return self.confirmed or self.proposed

    def _resolve(self, state, at, by):
        self.history.append({**self.pending_switch, 'state': state, 'resolved_at': at, 'resolved_by': by})
        self.pending_switch = None

    def select(self, name, at, *, source='operator_confirmed'):
        """Integration boundary: call only after the Store selection/session transaction commits."""
        if self.pending_switch:
            self._resolve('confirmed' if same_character_name(self.pending_switch['name'], name) else 'superseded', at,
                          'operator_selection' if source=='operator_confirmed' else source)
        self.confirmed, self.proposed, self.proposed_evidence, self.streak = name, None, [], []
        self.confirmation_source = source
        self.reference_seen_at = None

    def dismiss(self, at):
        """Operator rejected the pending switch; the same name needs two new frames to return."""
        if self.pending_switch:
            self._resolve('dismissed', at, 'operator')
            self.streak = []

    def snapshot(self, status):
        return dict(channel=self.channel, confirmed_name=self.confirmed, proposed_name=self.proposed,
                    proposed_evidence=self.proposed_evidence, reference_name=self.reference,
                    reference_source=self.confirmation_source if self.confirmed else 'ocr_proposed' if self.proposed else None,
                    pending_switch=dict(self.pending_switch) if self.pending_switch else None,
                    history=list(self.history),
                    confirming_name=self.streak[-1]['name'] if self.streak else None,
                    confirming_frames=len(self.streak), latest_status=status, trusted=False,
                    review_required=bool(self.pending_switch or (self.proposed and not self.confirmed)))

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
            pending = self.pending_switch
            if evidence['status'] != 'candidate':
                self.streak = []
            else:
                name = evidence['name']
                if same_character_name(name, self.reference):
                    self.reference_seen_at = when
                if pending and same_character_name(name, pending['name']):
                    pending['last_seen_at'] = evidence['received_at']
                if self.streak and not same_character_name(self.streak[-1]['name'], name):
                    self.streak = []
                reference = {k: evidence[k] for k in ('name', 'pixel_sha256', 'received_at', 'box', 'score')}
                self.streak = (self.streak + [reference])[-2:]
                if len(self.streak) == 2:
                    if self.reference is None or same_character_name(name, self.reference):
                        if pending:
                            self._resolve('superseded', evidence['received_at'], name)
                        self.proposed, self.proposed_evidence = name, list(self.streak)
                    elif pending and same_character_name(name, pending['name']):
                        pending['evidence'] = list(self.streak)
                    else:
                        if pending:
                            self._resolve('superseded', evidence['received_at'], name)
                        self.pending_switch = dict(kind='possible_character_switch', name=name, state='pending',
                            evidence=list(self.streak), created_at=evidence['received_at'],
                            last_seen_at=evidence['received_at'], review_required=True)
            pending = self.pending_switch
            # Absence of name evidence never clears a hold; expiry needs time AND the reference seen since.
            if pending and self.reference_seen_at:
                last = datetime.fromisoformat(pending['last_seen_at'])
                if self.reference_seen_at > last and (when - last).total_seconds() >= self.pending_ttl:
                    self._resolve('expired', evidence['received_at'], 'reference_seen_without_pending_name')
        return self.snapshot(reason)


class IdentityCapture:
    def __init__(self, channel, *, interval=0, confirmed=None, confirmation_source='operator_confirmed'):
        self.suggestions = IdentitySuggestions(channel, confirmed=confirmed,confirmation_source=confirmation_source)
        self.interval = interval
        self.last_check = None
        self.previous = None
        self.latest = None
        self.job = self.job_seen = self.job_checked = None

    def select(self, name, at, *, source='operator_confirmed'):
        """After a committed switch/new session; numbers never compare across characters."""
        self.suggestions.select(name, at, source=source)
        self.previous = None
        self.job = self.job_seen = self.job_checked = None

    def job_due(self, level, now):
        """Rare by design: each minute until two reads agree (or one disagrees with the known job),
        every 10 minutes once the level allows the next job, otherwise never."""
        if self.job is None or self.job_seen != self.job:
            wait = JOB_RETRY_SECONDS
        elif level is not None and (advance := next_level(self.job)) is not None and level >= advance:
            wait = JOB_RECHECK_SECONDS
        else:
            return False
        return self.job_checked is None or now - self.job_checked >= wait

    def read_job(self, image, layout, read_name, now):
        """One read of the job line; two agreeing reads make it known, and it only moves up a tier."""
        self.job_checked = now
        box = job_region(layout, image.size)
        raw = read_name(image.crop(box)).get('raw') or {}
        texts, scores = raw.get('txts'), raw.get('scores')
        text = texts[0] if isinstance(texts, list) and len(texts) == 1 and isinstance(texts[0], str) and len(texts[0]) <= 160 else None
        score = (scores[0] if isinstance(scores, list) and len(scores) == 1 and type(scores[0]) in (int, float)
                 and math.isfinite(scores[0]) else None)
        job = match(text) if score is not None and score >= .9 else None
        if job and job == self.job_seen and (self.job is None or tier(job) > tier(self.job)):
            self.job = job
        self.job_seen = job
        return dict(status='candidate' if job else 'unrecognized', job=job, tier=job and tier(job),
                    text=text, score=score, box=box)

    def numeric_check(self, result, received_at, requirements):
        """Use the existing transition validator and both existing rounding hypotheses."""
        pair, level = result.get('candidate'), result.get('visual_level')
        if not result.get('current') or pair is None or level is None:
            return dict(check_now=bool(result.get('current') and (self.previous or self.suggestions.reference)),
                        reason='numeric_unavailable', classification='unknown')
        checks = {mode: assess(level, pair[0], pair[1], requirements, mode) for mode in MODES}
        if all(c['status'] == 'inconsistent' for c in checks.values()):
            return dict(check_now=True, reason='contradicts_both_display_hypotheses',
                        classification='possible_bad_ocr', arithmetic=checks)
        current = self.latest = Observation(self.suggestions.channel, datetime.fromisoformat(received_at),
                                            Reading(level, *pair))
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
        needs_confirmation = self.suggestions.reference is None or bool(self.suggestions.streak and
            not same_character_name(self.suggestions.streak[-1]['name'], self.suggestions.reference))
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
                def parsed(response):
                    texts, scores = (response.get('raw') or {}).get('txts'), (response.get('raw') or {}).get('scores')
                    if (isinstance(texts, list) and len(texts) == 1 and isinstance(texts[0], str)
                            and len(texts[0]) <= 160 and isinstance(scores, list) and len(scores) == 1
                            and type(scores[0]) in (int, float) and math.isfinite(scores[0]) and 0 <= scores[0] <= 1):
                        return scores[0], name_text(texts[0]) if scores[0] >= .5 else None
                    return None
                crop = image.crop(region['box'])
                response = read_name(clean_name_crop(crop)); read = parsed(response)
                reference = self.suggestions.reference
                if reference and not same_character_name((read or (0, None))[1], reference):
                    # Only a matching current-character name replaces the plain read.
                    second = read_name(second_look(crop))
                    if same_character_name((parsed(second) or (0, None))[1], reference):
                        evidence['first_read'] = dict(text=response.get('text'), score=read and read[0])
                        response, read = second, parsed(second)
                evidence['raw'] = response
                if read:
                    evidence['score'], evidence['name'] = read
                evidence['status'] = 'candidate' if evidence['name'] else 'unreadable_or_conflicting'
                level = result.get('visual_level') or (result.get('neural_level') or {}).get('level')
                if self.job_due(level, started):
                    try:  # The job is a bonus: a failed job read never costs this frame its name read.
                        evidence['job'] = self.read_job(image, layouts[0], read_name, started)
                    except (OSError, RuntimeError, ValueError, KeyError) as error:
                        evidence['job'] = dict(status='failed', error=type(error).__name__)
            except (OSError, RuntimeError, ValueError, KeyError) as error:
                evidence.update(status='failed', error=type(error).__name__)
        if clock() - frame.arrived_monotonic > max_age:
            evidence.update(status='stale_local_frame', name=None)
            if evidence.get('job'):evidence['job'].update(status='stale_local_frame', job=None, tier=None)
        evidence['seconds'] = clock() - started
        if evidence['status'] == 'not_due':
            # Skipping work must not manufacture another vote or break a real confirmation.
            suggestion = self.suggestions.snapshot('not_due')
        else:
            suggestion = self.suggestions.observe(evidence)
        reference, observed, pending = suggestion['reference_name'], evidence['name'], suggestion['pending_switch']
        mismatch = bool(observed and reference and not same_character_name(observed, reference))
        verified = bool(observed and same_character_name(observed, reference))
        conflict = dict(reference_name=reference, reference_source=suggestion['reference_source'],
                        observed_name=observed if mismatch else None,
                        pending_name=pending['name'] if pending else None) if mismatch or pending else None
        anomaly = numeric['classification'] in OWNERSHIP_RISK
        hold = [r for r, on in (('name_mismatch', mismatch), ('pending_switch', bool(pending)),
                                ('unverified_numeric_anomaly', anomaly and not verified)) if on]
        # A same-character change (name verified, or the existing wrap rule) becomes the next comparison anchor.
        if (numeric.get('transition', {}).get('status') == 'ambiguous' and not conflict
                and (verified or numeric['classification'] == 'possible_normal_level_up')):
            self.previous = self.latest
        return dict(evidence=evidence, suggestion=suggestion, numeric_check=numeric,
                    verification_requested=bool(numeric['check_now'] or needs_confirmation),
                    identity_conflict=conflict, reading_hold_recommended=bool(hold), hold_reasons=hold,
                    tracking_action='none')

    def missing(self, received_at):
        return self.suggestions.observe(dict(status='capture_failed', received_at=received_at, pixel_sha256=None))
