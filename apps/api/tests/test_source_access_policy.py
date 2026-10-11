from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from miy_api.domains.auth.models import User
from miy_api.domains.pms.space_models import Team, TeamMember
from miy_api.domains.auth.security import new_id


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _user(db, email: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    assert user is not None
    return user


def _new_space(db) -> Team:
    team = Team(id=new_id(), key=new_id(), name="Source ACL space")
    db.add(team)
    db.flush()
    return team


def _ensure_team_member(db, *, team: Team, user: User) -> None:
    existing = db.scalar(
        select(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == user.id)
    )
    if existing is None:
        db.add(TeamMember(id=new_id(), team_id=team.id, user_id=user.id, role="member"))
