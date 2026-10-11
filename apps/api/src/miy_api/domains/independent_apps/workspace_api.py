"""Explicit workspace grants extend delivery to owned temporary installations."""

from uuid import UUID

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from miy_api.core.db import get_db_session
from miy_api.domains.independent_apps import delegation, delivery, service, workspaces
from miy_api.domains.independent_apps.delegation_contracts import BuildInput, BuildOut
from miy_api.domains.independent_apps.delivery_contracts import DeploymentInput, DeploymentOut
from miy_api.domains.independent_apps.delivery_models import AppBuildJob, AppDeploymentRequest
from miy_api.domains.independent_apps.workspace_contracts import (
    WorkspaceOut,
    WorkspacePrepare,
    WorkspaceSync,
    WorkspaceTransition,
    WorkspaceIntegrate,
    WorkspaceComplete,
)

router = APIRouter()
BASE = "/delegated/{app_id}/installations/{installation_id}/workspaces/{workspace_id}"


def access(
    app_id: str,
    installation_id: UUID,
    authorization: str | None = Header(default=None, max_length=200),
    db: Session = Depends(get_db_session),
):
    grant, context = delegation.resolve(
        db, authorization, "workspace", app_id, str(installation_id)
    )
    return db, grant, context


@router.post(BASE + "/prepare", response_model=WorkspaceOut)
def workspace_prepare(workspace_id: UUID, data: WorkspacePrepare, auth=Depends(access)):
    db, grant, context = auth
    return workspaces.prepare(db, workspace_id, data, grant, context)


@router.get(BASE + "/context", response_model=WorkspaceOut)
def workspace_context(workspace_id: UUID, auth=Depends(access)):
    db, grant, actor = auth
    return workspaces.snapshot(db, workspaces.require(db, workspace_id, grant, actor))


@router.post(BASE + "/sync", response_model=WorkspaceOut)
def workspace_sync(workspace_id: UUID, data: WorkspaceSync, auth=Depends(access)):
    db, grant, context = auth
    delegation.validate(db, grant, "sync", grant.app_id, grant.installation_id)
    return workspaces.sync(db, workspace_id, data, grant, context)


@router.post(BASE + "/builds", response_model=BuildOut, status_code=202)
def workspace_build(workspace_id: UUID, data: BuildInput, auth=Depends(access)):
    db, grant, context = auth
    row = workspaces.require(db, workspace_id, grant, context)
    return delegation.request_build(db, grant, context, data, installation_id=row.installation_id)


@router.get(BASE + "/builds/{build_id}", response_model=BuildOut)
def workspace_build_status(workspace_id: UUID, build_id: UUID, auth=Depends(access)):
    db, grant, context = auth
    row = workspaces.require(db, workspace_id, grant, context)
    job = db.get(AppBuildJob, str(build_id))
    if job is None or (job.app_id, job.installation_id, job.actor_user_id) != (
        row.app_id,
        row.installation_id,
        context.user.id,
    ):
        service.fail("not_found", 404)
    return delegation.build_out(job)


@router.post(BASE + "/deployments", response_model=DeploymentOut, status_code=202)
def workspace_deploy(workspace_id: UUID, data: DeploymentInput, auth=Depends(access)):
    db, grant, context = auth
    row = workspaces.require(db, workspace_id, grant, context)
    if str(data.installation_id) != row.installation_id:
        service.fail("forbidden")
    delegation.validate(db, grant, data.action, row.app_id, row.installation_id)
    return delivery.request_deployment(db, row.app_id, data, context, delegation_id=grant.id)


@router.get(BASE + "/deployments/{request_id}", response_model=DeploymentOut)
def workspace_deployment_status(workspace_id: UUID, request_id: UUID, auth=Depends(access)):
    db, grant, context = auth
    row = workspaces.require(db, workspace_id, grant, context)
    item = db.get(AppDeploymentRequest, str(request_id))
    if item is None or (item.installation_id, item.actor_user_id) != (
        row.installation_id,
        context.user.id,
    ):
        service.fail("not_found", 404)
    return delivery.deployment_out(item)


@router.post(BASE + "/stop", response_model=WorkspaceOut)
def workspace_stop(workspace_id: UUID, data: WorkspaceTransition, auth=Depends(access)):
    return workspaces.transition(*auth, workspace_id, data, action="stop")


@router.post(BASE + "/resume", response_model=WorkspaceOut)
def workspace_resume(workspace_id: UUID, data: WorkspaceTransition, auth=Depends(access)):
    return workspaces.transition(*auth, workspace_id, data, action="resume")


@router.post(BASE + "/cleanup", response_model=WorkspaceOut)
def workspace_cleanup(workspace_id: UUID, data: WorkspaceTransition, auth=Depends(access)):
    return workspaces.transition(*auth, workspace_id, data, action="cleanup")


@router.post(BASE + "/integrate", response_model=WorkspaceOut)
def workspace_integrate(workspace_id: UUID, data: WorkspaceIntegrate, auth=Depends(access)):
    return workspaces.integrate(*auth, workspace_id, data)


@router.post(BASE + "/complete", response_model=WorkspaceOut)
def workspace_complete(workspace_id: UUID, data: WorkspaceComplete, auth=Depends(access)):
    return workspaces.confirm_integration(*auth, workspace_id, data.deployment_id)
