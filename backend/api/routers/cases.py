"""Cases CRUD, CSV upload + DuckDB ingest, preview, activity."""
from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

import polars as pl
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import case as sql_case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.coordinator import build_persona_suggestion
from backend.case_status import normalize_case_status
from backend.config import settings
from backend.data.tenant_constants import DEFAULT_TENANT_ID
from backend.data.warehouse import GlobalWarehouse
from backend.database import get_db
from backend.database.dataset_path_resolve import resolve_with_active_fallback_async
from backend.database.ingestion_pipeline import ingest_csv_with_fallback
from backend.database.models import AuditLog, Case, CaseShare, CaseWorkbenchPins, Lead
from backend.schemas import (
    ActivityBulkRequest,
    ActivityBulkResponse,
    ActivitySeriesPayload,
    CaseCreate,
    CaseOut,
    CasePatch,
    CaseShareCreate,
    CaseShareOut,
    CasesPurgeOut,
    EvidenceBoardResponse,
    LeadOut,
    LeadStatusPatch,
    AuditLogOut,
    WorkbenchPinsOut,
    WorkbenchPinsPut,
)
from backend.tools.case_activity import compute_case_activity

router = APIRouter(prefix="/api/cases", tags=["cases"])
_log = logging.getLogger(__name__)

_STATUS_SORT = sql_case(
    (Case.status == "FLAGGED", 0),
    (Case.status == "INVESTIGATING", 1),
    (Case.status == "CLEARED", 2),
    else_=3,
)


class SnowflakeIngestRequest(BaseModel):
    name: str
    status: str = "INVESTIGATING"
    account: str
    user: str
    password: str
    warehouse: str
    database: str
    schema_name: str
    query: str


class BigQueryIngestRequest(BaseModel):
    name: str
    status: str = "INVESTIGATING"
    project_id: str
    credentials_json: str
    query: str


async def _memory_aggregates(
    db: AsyncSession, ids: list[str]
) -> tuple[dict[str, int], dict[str, tuple[int, datetime | None, int]]]:
    if not ids:
        return {}, {}
    lead_result = await db.execute(
        select(Lead.case_id, func.count(Lead.id)).where(Lead.case_id.in_(ids)).group_by(Lead.case_id)
    )
    lead_counts = {str(row[0]): int(row[1]) for row in lead_result.all()}
    aud_result = await db.execute(
        select(
            AuditLog.case_id,
            func.count(AuditLog.id).label("ev"),
            func.max(AuditLog.timestamp).label("last_ts"),
            func.sum(sql_case((AuditLog.code_executed.isnot(None), 1), else_=0)).label("scripts"),
        )
        .where(AuditLog.case_id.in_(ids))
        .group_by(AuditLog.case_id)
    )
    aud: dict[str, tuple[int, datetime | None, int]] = {}
    for r in aud_result.mappings().all():
        scripts_val = r.get("scripts")
        ts = r.get("last_ts")
        cid_key = str(r["case_id"])
        aud[cid_key] = (
            int(r["ev"] or 0),
            ts if isinstance(ts, datetime) else None,
            int(scripts_val or 0),
        )
    return lead_counts, aud


async def _case_to_out(db: AsyncSession, row: Case) -> CaseOut:
    lc, aud = await _memory_aggregates(db, [row.id])
    n_lead = lc.get(row.id, 0)
    ev, last_ts, n_script = aud.get(row.id, (0, None, 0))
    return CaseOut(
        id=row.id,
        tenant_id=str(getattr(row, "tenant_id", None) or DEFAULT_TENANT_ID),
        name=row.name,
        dataset_path=row.dataset_path,
        duckdb_path=row.duckdb_path,
        is_active=row.is_active,
        status=normalize_case_status(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        schema_summary=row.schema_summary,
        lead_count=n_lead,
        evidence_event_count=ev,
        script_run_count=n_script,
        last_memory_at=last_ts,
        persona_suggestion=build_persona_suggestion(row.schema_summary if isinstance(row.schema_summary, dict) else None),
    )


@router.get("", response_model=list[CaseOut])
async def list_cases(db: AsyncSession = Depends(get_db)) -> list[CaseOut]:
    result = await db.execute(select(Case).order_by(_STATUS_SORT.asc(), Case.created_at.desc()))
    cases = result.scalars().all()
    if not cases:
        return []
    return [await _case_to_out(db, c) for c in cases]


@router.post("/ingest/snowflake", response_model=CaseOut)
async def ingest_snowflake(body: SnowflakeIngestRequest, db: AsyncSession = Depends(get_db)) -> CaseOut:
    try:
        import snowflake.connector
    except ImportError:
        raise HTTPException(500, "snowflake-connector-python not installed")

    try:
        conn = snowflake.connector.connect(
            user=body.user,
            password=body.password,
            account=body.account,
            warehouse=body.warehouse,
            database=body.database,
            schema=body.schema_name,
        )
        cur = conn.cursor()
        cur.execute(body.query)
        df = cur.fetch_pandas_all()
        conn.close()
    except Exception as e:
        raise HTTPException(400, f"Snowflake query failed: {e}") from e

    if df.empty:
        raise HTTPException(400, "Query returned no rows")

    cid = str(uuid.uuid4())
    filename = f"{cid}_snowflake.parquet"
    out_path = settings.datasets_storage_dir / filename

    pldf = pl.from_pandas(df)
    pldf.write_parquet(str(out_path))
    tmp_csv = out_path.with_suffix(".csv")
    try:
        pldf.write_csv(tmp_csv)
        dest_csv, duck_path, schema_summary = ingest_csv_with_fallback(cid, tmp_csv, f"{cid}.csv")
    finally:
        tmp_csv.unlink(missing_ok=True)

    try:
        GlobalWarehouse(tenant_id=DEFAULT_TENANT_ID).append_case_csv(cid, dest_csv, filename)
    except Exception as wh_exc:  # noqa: BLE001
        _log.warning("Warehouse append failed for %s: %s", cid, wh_exc)

    case = Case(
        id=cid,
        name=body.name,
        tenant_id=DEFAULT_TENANT_ID,
        dataset_path=str(dest_csv.resolve()),
        duckdb_path=str(duck_path.resolve()),
        schema_summary=schema_summary,
        status=normalize_case_status(body.status),
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return await _case_to_out(db, case)


@router.post("/ingest/bigquery", response_model=CaseOut)
async def ingest_bigquery(body: BigQueryIngestRequest, db: AsyncSession = Depends(get_db)) -> CaseOut:
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ImportError:
        raise HTTPException(500, "google-cloud-bigquery not installed")

    try:
        import json

        creds_info = json.loads(body.credentials_json)
        credentials = service_account.Credentials.from_service_account_info(creds_info)
        client = bigquery.Client(credentials=credentials, project=body.project_id)

        query_job = client.query(body.query)
        df = query_job.to_dataframe()
    except Exception as e:
        raise HTTPException(400, f"BigQuery query failed: {e}") from e

    if df.empty:
        raise HTTPException(400, "Query returned no rows")

    cid = str(uuid.uuid4())
    filename = f"{cid}_bigquery.parquet"
    out_path = settings.datasets_storage_dir / filename

    pldf = pl.from_pandas(df)
    pldf.write_parquet(str(out_path))
    tmp_csv = out_path.with_suffix(".csv")
    try:
        pldf.write_csv(tmp_csv)
        dest_csv, duck_path, schema_summary = ingest_csv_with_fallback(cid, tmp_csv, f"{cid}.csv")
    finally:
        tmp_csv.unlink(missing_ok=True)

    try:
        GlobalWarehouse(tenant_id=DEFAULT_TENANT_ID).append_case_csv(cid, dest_csv, filename)
    except Exception as wh_exc:  # noqa: BLE001
        _log.warning("Warehouse append failed for %s: %s", cid, wh_exc)

    case = Case(
        id=cid,
        name=body.name,
        tenant_id=DEFAULT_TENANT_ID,
        dataset_path=str(dest_csv.resolve()),
        duckdb_path=str(duck_path.resolve()),
        schema_summary=schema_summary,
        status=normalize_case_status(body.status),
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return await _case_to_out(db, case)


@router.post("/upload", response_model=CaseOut)
async def upload_case(
    name: str = Form(...),
    status: str = Form(default="INVESTIGATING"),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> CaseOut:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "A .csv file is required")
    label = (name or "").strip() or "Untitled case"
    st = normalize_case_status(status)
    case_id = str(uuid.uuid4())
    tenant_id = DEFAULT_TENANT_ID

    suffix = Path(file.filename).suffix or ".csv"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        dest_csv, duck_path, summary = ingest_csv_with_fallback(case_id, tmp_path, file.filename)
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Ingestion failed: {e}") from e
    tmp_path.unlink(missing_ok=True)

    try:
        GlobalWarehouse(tenant_id=tenant_id).append_case_csv(case_id, dest_csv, file.filename)
    except Exception as wh_exc:  # noqa: BLE001
        _log.warning("Global warehouse append failed for %s: %s", case_id, wh_exc)

    case = Case(
        id=case_id,
        name=label,
        tenant_id=tenant_id,
        dataset_path=str(dest_csv.resolve()),
        is_active=False,
        status=st,
        duckdb_path=str(duck_path.resolve()),
        schema_summary=summary,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return await _case_to_out(db, case)


@router.post("", response_model=CaseOut)
async def create_case(body: CaseCreate, db: AsyncSession = Depends(get_db)) -> CaseOut:
    st = normalize_case_status(body.status)
    tid = (body.tenant_id or DEFAULT_TENANT_ID).strip() or DEFAULT_TENANT_ID
    case = Case(
        id=str(uuid.uuid4()),
        name=body.name,
        tenant_id=tid,
        dataset_path=body.dataset_path,
        is_active=False,
        status=st,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return await _case_to_out(db, case)


def _remove_case_disk_warehouse(case: Case) -> None:
    try:
        tid = str(getattr(case, "tenant_id", None) or DEFAULT_TENANT_ID).strip() or DEFAULT_TENANT_ID
        GlobalWarehouse(tenant_id=tid).remove_case(case.id)
    except Exception as exc:  # noqa: BLE001
        _log.warning("Global warehouse remove failed for %s: %s", case.id, exc)
    case_dir = settings.datasets_storage_dir / case.id
    if case_dir.is_dir():
        shutil.rmtree(case_dir, ignore_errors=True)
    if case.duckdb_path:
        try:
            Path(case.duckdb_path).unlink(missing_ok=True)
        except OSError as exc:
            _log.warning("DuckDB unlink %s: %s", case.duckdb_path, exc)


async def _purge_all_cases_impl(db: AsyncSession) -> CasesPurgeOut:
    result = await db.execute(select(Case).order_by(Case.created_at.asc()))
    rows = list(result.scalars().all())
    n = 0
    for c in rows:
        _remove_case_disk_warehouse(c)
        db.delete(c)
        n += 1
    await db.commit()
    return CasesPurgeOut(ok=True, cases_removed=n)


@router.post("/purge-all", response_model=CasesPurgeOut)
async def purge_all_cases_post(db: AsyncSession = Depends(get_db)) -> CasesPurgeOut:
    return await _purge_all_cases_impl(db)


@router.delete("/purge-all", response_model=CasesPurgeOut)
async def purge_all_cases_delete(db: AsyncSession = Depends(get_db)) -> CasesPurgeOut:
    return await _purge_all_cases_impl(db)


@router.delete("/{case_id}")
async def delete_case(case_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    result = await db.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(404, "Case not found")
    was_active = case.is_active
    _remove_case_disk_warehouse(case)
    db.delete(case)
    await db.commit()
    if was_active:
        rem = await db.execute(select(Case).order_by(Case.created_at.desc()).limit(1))
        remaining = rem.scalar_one_or_none()
        if remaining:
            all_c = await db.execute(select(Case))
            for x in all_c.scalars().all():
                x.is_active = x.id == remaining.id
            await db.commit()
    return {"ok": True}


@router.post("/activity-bulk", response_model=ActivityBulkResponse)
async def activity_bulk(body: ActivityBulkRequest, db: AsyncSession = Depends(get_db)) -> ActivityBulkResponse:
    raw_ids = list(dict.fromkeys(body.case_ids))[:64]
    out: dict[str, ActivitySeriesPayload] = {}
    for cid in raw_ids:
        r = await db.execute(select(Case).where(Case.id == cid))
        case = r.scalar_one_or_none()
        path = case.dataset_path if case else None
        payload = compute_case_activity(cid, path)
        out[cid] = ActivitySeriesPayload(**payload)
    return ActivityBulkResponse(activities=out)


@router.patch("/{case_id}", response_model=CaseOut)
async def patch_case(case_id: str, body: CasePatch, db: AsyncSession = Depends(get_db)) -> CaseOut:
    result = await db.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(404, "Case not found")
    if body.name is not None:
        case.name = body.name
    if body.status is not None:
        case.status = normalize_case_status(body.status)
    await db.commit()
    await db.refresh(case)
    return await _case_to_out(db, case)


@router.post("/{case_id}/activate", response_model=CaseOut)
async def activate_case(case_id: str, db: AsyncSession = Depends(get_db)) -> CaseOut:
    all_c = await db.execute(select(Case))
    for c in all_c.scalars().all():
        c.is_active = c.id == case_id
    await db.commit()
    result = await db.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(404, "Case not found")
    return await _case_to_out(db, case)


@router.get("/{case_id}/evidence", response_model=EvidenceBoardResponse)
async def get_evidence(case_id: str, db: AsyncSession = Depends(get_db)) -> EvidenceBoardResponse:
    result = await db.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(404, "Case not found")
    leads_r = await db.execute(select(Lead).where(Lead.case_id == case_id).order_by(Lead.created_at.desc()))
    leads = leads_r.scalars().all()
    aud_r = await db.execute(
        select(AuditLog)
        .where(AuditLog.case_id == case_id)
        .order_by(AuditLog.timestamp.asc(), AuditLog.id.asc())
    )
    audits = aud_r.scalars().all()
    return EvidenceBoardResponse(
        leads=[LeadOut.model_validate(x) for x in leads],
        audit_logs=[AuditLogOut.model_validate(x) for x in audits],
    )


@router.patch("/{case_id}/leads/{lead_id}", response_model=LeadOut)
async def patch_lead(case_id: str, lead_id: str, body: LeadStatusPatch, db: AsyncSession = Depends(get_db)) -> Lead:
    result = await db.execute(select(Lead).where(Lead.id == lead_id, Lead.case_id == case_id))
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(404, "Lead not found")
    lead.status = body.status
    await db.commit()
    await db.refresh(lead)
    return lead


@router.get("/{case_id}/workbench-pins", response_model=WorkbenchPinsOut)
async def get_workbench_pins(case_id: str, db: AsyncSession = Depends(get_db)) -> WorkbenchPinsOut:
    result = await db.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(404, "Case not found")
    row_r = await db.execute(select(CaseWorkbenchPins).where(CaseWorkbenchPins.case_id == case_id))
    row = row_r.scalar_one_or_none()
    if not row or not row.pins_json:
        return WorkbenchPinsOut(pins=[])
    pins = row.pins_json if isinstance(row.pins_json, list) else []
    return WorkbenchPinsOut(pins=pins[:24])


@router.put("/{case_id}/workbench-pins", response_model=WorkbenchPinsOut)
async def put_workbench_pins(case_id: str, body: WorkbenchPinsPut, db: AsyncSession = Depends(get_db)) -> WorkbenchPinsOut:
    result = await db.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(404, "Case not found")
    raw = [p.model_dump(by_alias=True) for p in body.pins[:24]]
    row_r = await db.execute(select(CaseWorkbenchPins).where(CaseWorkbenchPins.case_id == case_id))
    row = row_r.scalar_one_or_none()
    if row:
        row.pins_json = raw
    else:
        db.add(CaseWorkbenchPins(case_id=case_id, pins_json=raw))
    await db.commit()
    return WorkbenchPinsOut(pins=raw)


@router.get("/{case_id}/shares", response_model=list[CaseShareOut])
async def list_case_shares(case_id: str, db: AsyncSession = Depends(get_db)) -> list[CaseShareOut]:
    own = await db.execute(select(Case).where(Case.id == case_id))
    if own.scalar_one_or_none() is None:
        raise HTTPException(404, "Case not found")
    sh = await db.execute(select(CaseShare).where(CaseShare.owner_case_id == case_id).order_by(CaseShare.id.asc()))
    rows = sh.scalars().all()
    return [CaseShareOut.model_validate(r) for r in rows]


@router.post("/{case_id}/shares", response_model=CaseShareOut, status_code=201)
async def create_case_share(
    case_id: str,
    body: CaseShareCreate,
    db: AsyncSession = Depends(get_db),
) -> CaseShareOut:
    owner_r = await db.execute(select(Case).where(Case.id == case_id))
    owner = owner_r.scalar_one_or_none()
    if not owner:
        raise HTTPException(404, "Owner case not found")
    vid = (body.viewer_case_id or "").strip()
    if not vid or vid == case_id:
        raise HTTPException(400, "viewer_case_id must be set and different from owner case")
    viewer_r = await db.execute(select(Case).where(Case.id == vid))
    viewer = viewer_r.scalar_one_or_none()
    if not viewer:
        raise HTTPException(404, "Viewer case not found")
    if str(owner.tenant_id) != str(viewer.tenant_id):
        raise HTTPException(400, "Cases must belong to the same tenant to share warehouse data")
    row = CaseShare(owner_case_id=case_id, viewer_case_id=vid)
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Share already exists or violates constraints") from exc
    await db.refresh(row)
    return CaseShareOut.model_validate(row)


@router.delete("/{case_id}/shares/{viewer_case_id}")
async def delete_case_share(case_id: str, viewer_case_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, bool]:
    r = await db.execute(
        select(CaseShare).where(CaseShare.owner_case_id == case_id, CaseShare.viewer_case_id == viewer_case_id)
    )
    row = r.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Share not found")
    db.delete(row)
    await db.commit()
    return {"ok": True}


@router.get("/{case_id}/preview")
async def preview(case_id: str, rows: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Case).where(Case.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        raise HTTPException(400, "Case or dataset path missing")
    path = await resolve_with_active_fallback_async(db, case.dataset_path)
    if not path:
        raise HTTPException(400, "Case or dataset path missing")
    df = pl.read_csv(path, try_parse_dates=True, n_rows=rows)
    return {"columns": df.columns, "rows": df.to_dicts()}
