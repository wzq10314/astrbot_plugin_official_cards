"""Opaque callback actions bound to their real QQ destination and requester."""
from collections import OrderedDict
import re
import secrets
import time

from .keyboard_pages import event_owner
from .button_prompts import _safe_text


SCENES = {'GroupMessage': 'group', 'PatchedGroupMessage': 'group',
          'C2CMessage': 'c2c', 'PatchedC2CMessage': 'c2c'}


class CallbackActionStore:
    def __init__(self, *, ttl=3600, max_entries=4096, clock=time.monotonic):
        self.ttl = max(1, min(float(ttl), 3600))
        self.max_entries = max(1, min(int(max_entries), 4096))
        self.clock, self.entries = clock, OrderedDict()

    def clear(self):
        self.entries.clear()

    def _cleanup(self):
        for token, entry in list(self.entries.items()):
            if entry[0] <= self.clock():
                del self.entries[token]

    def create(self, command, event=None, *, scope=None):
        if not _safe_text(command):
            return None
        owner = event_owner(event)
        if owner:
            platform, scene, session, sender, _ = owner
            scene = SCENES.get(scene)
        elif scope is not None:
            platform, scene, session = scope
            sender = None
        else:
            return None
        if scene not in {'group', 'c2c'} or not all(
            isinstance(value, str) and value for value in (platform, session)
        ):
            return None
        self._cleanup()
        token = 'oc:' + secrets.token_urlsafe(18)
        self.entries[token] = (self.clock() + self.ttl, platform, scene, session, sender, command)
        while len(self.entries) > self.max_entries:
            self.entries.popitem(last=False)
        # C2C clients may reject a specified-user keyboard before emitting its
        # callback. Permit the tap there; resolve() still checks the exact
        # platform, private destination and requester on the server.
        permission = {'type': 0, 'specify_user_ids': [sender]} if sender and scene == 'group' else {'type': 2}
        return {'type': 1, 'data': token, 'permission': permission,
                'unsupport_tips': '请更新 QQ 后重试，或使用菜单中的命令'}

    def resolve(self, token, *, platform_id, scene, session, sender):
        if not isinstance(token, str) or not re.fullmatch(r'oc:[A-Za-z0-9_-]{24}', token):
            return None
        if not isinstance(sender, str) or not sender:
            return None
        self._cleanup()
        entry = self.entries.get(token)
        if entry is None or (platform_id, scene, session) != entry[1:4]:
            return None
        if entry[4] is not None and sender != entry[4]:
            return None
        return entry[5]
