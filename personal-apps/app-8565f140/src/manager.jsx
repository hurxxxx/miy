import React, {useEffect, useRef, useState} from 'react';
import {emptyEquipment, samples, filterEquipment, normalizeEquipment, equipmentNumberError} from './equipment.mjs';

export default function EquipmentManager({token, onExpired}) {
  const [items, setItems] = useState([]), [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  const [query, setQuery] = useState(''), [status, setStatus] = useState('');
  const [editing, setEditing] = useState(null), [form, setForm] = useState(null);
  const [uncertain, setUncertain] = useState(null);
  const alive = useRef(true);
  async function request(path, options = {}) {
    const response = await fetch(path, {...options, headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'}, credentials: 'omit', cache: 'no-store'});
    if (!response.ok) {
      if (response.status === 401) onExpired();
      if (response.status === 403) {setItems([]); setLoaded(false);}
      const error = new Error('request'); error.status = response.status; throw error;
    }
    return response.json();
  }
  function describe(error) {
    return error.status === 403 ? '저장 권한 또는 저장 기능 연결이 필요합니다.' : error.status === 401 ? '연결이 만료되었습니다. 다시 연결해 주세요.' : error.status === 422 ? '입력값을 확인해 주세요.' : '처리하지 못했습니다. 잠시 후 다시 확인해 주세요.';
  }
  async function load() {
    let all = [], cursor = null;
    const seen = new Set();
    do {
      const page = await request('/api/equipment' + (cursor ? `?after=${encodeURIComponent(cursor)}` : ''));
      all.push(...page.items); cursor = page.next_cursor;
      if (cursor && seen.has(cursor)) throw new Error('Invalid pagination');
      seen.add(cursor);
    } while (cursor);
    if (alive.current) {setItems(all); setLoaded(true);}
  }
  async function refresh() {
    setBusy(true); setMessage('');
    try {await load();} catch (error) {setMessage(describe(error));}
    finally {if (alive.current) setBusy(false);}
  }
  useEffect(() => {alive.current = true; void refresh(); return () => {alive.current = false;};}, [token]);

  async function create(payload) {
    try {return await request('/api/equipment', {method: 'POST', body: JSON.stringify(payload)});}
    catch (error) {
      if (!error.status || error.status >= 500) {
        try {
          const record = await request(`/api/equipment/by-number?number=${encodeURIComponent(payload.number)}`);
          if (Object.keys(payload).every(key => record.payload[key] === payload[key])) return record;
          const duplicate = new Error('duplicate'); duplicate.status = 409; throw duplicate;
        } catch (lookup) {
          if (lookup.status === 409) throw lookup;
          setUncertain(payload.number);
          throw new Error('unknown');
        }
      }
      throw error;
    }
  }
  async function checkUncertain() {
    setBusy(true);
    try {
      await request(`/api/equipment/by-number?number=${encodeURIComponent(uncertain)}`);
      setUncertain(null); await load(); setMessage('해당 관리번호의 저장된 자료를 확인했습니다. 목록에서 내용을 확인해 주세요.');
    } catch (error) {
      if (error.status === 404) {setUncertain(null); setMessage('저장된 자료가 없습니다. 입력을 확인한 뒤 다시 저장할 수 있습니다.');}
      else setMessage(describe(error));
    } finally {setBusy(false);}
  }
  async function save(event) {
    event.preventDefault(); setBusy(true); setMessage('');
    const payload = normalizeEquipment(form);
    const numberError = equipmentNumberError(payload.number);
    if (numberError) {setMessage(numberError); setBusy(false); return;}
    if (!payload.name || !payload.number || !payload.location || (payload.status === 'in_use' && !payload.user)) {
      setMessage('장비 이름, 관리번호, 위치와 사용 중인 장비의 사용자 이름을 입력해 주세요.'); setBusy(false); return;
    }
    try {
      if (editing) await request(`/api/equipment/${editing.id}`, {method: 'PUT', body: JSON.stringify({...payload, expected_version: editing.version})});
      else await create(payload);
      setForm(null); setEditing(null); setMessage('저장했습니다.');
      try {await load();} catch {setMessage('저장은 완료됐지만 목록을 갱신하지 못했습니다. 새로고침해 주세요.');}
    } catch (error) {
      if (error.status === 409 && editing) {
        try {
          const latest = await request(`/api/equipment/${editing.id}`);
          setEditing(latest); setForm(latest.payload);
          setMessage('다른 창에서 변경되었습니다. 최신 내용을 표시했습니다. 다시 수정해 주세요.');
        } catch (readError) {setMessage(describe(readError));}
      } else setMessage(error.status === 409 ? '이미 등록된 관리번호입니다.' : describe(error));
    } finally {setBusy(false);}
  }
  async function addSamples() {
    setBusy(true); setMessage('');
    try {for (const sample of samples) await create(sample); setMessage('가짜 예시를 추가했습니다.');}
    catch (error) {setMessage(error.status === 409 ? '예시 관리번호가 이미 있습니다. 목록을 확인해 주세요.' : describe(error));}
    finally {try {await load();} catch (error) {setMessage(describe(error));} setBusy(false);}
  }
  const visible = filterEquipment(items, query, status);
  return <section aria-label="장비 관리">
    <p className="muted">본인만 볼 수 있는 목록입니다. 시험할 때는 가짜 사용자 정보를 입력해 주세요.</p>
    <div className="toolbar">
      <button disabled={busy || !loaded || !!uncertain} onClick={() => {setEditing(null); setForm(emptyEquipment());}}>새 장비 등록</button>
      <button disabled={busy} onClick={refresh}>새로고침</button>
      {loaded && !items.length && <button disabled={busy || !!uncertain} onClick={addSamples}>가짜 예시 2개 추가</button>}
    </div>
    <p role="status">{busy ? '처리 중…' : message}</p>
    {uncertain && <div role="alert">관리번호 {uncertain}의 저장 결과를 확인해야 합니다. <button disabled={busy} onClick={checkUncertain}>저장 여부 확인</button></div>}
    {form && <form onSubmit={save}>
      <h2>{editing ? '장비 수정' : '새 장비 등록'}</h2>
      <fieldset disabled={busy || !!uncertain}>
        {[['name','장비 이름'],['number','관리번호'],['user','사용하는 사람'],['location','위치']].map(([key,label]) => <label key={key}>{label}<input value={form[key]} maxLength={key === 'number' ? undefined : 100} required={key !== 'user' || form.status === 'in_use'} disabled={(key === 'number' && !!editing) || (key === 'user' && form.status === 'stored')} onChange={event => setForm({...form, [key]: event.target.value})}/></label>)}
        <label>상태<select value={form.status} onChange={event => setForm({...form, status: event.target.value, user: event.target.value === 'stored' ? '' : form.user})}><option value="stored">보관 중</option><option value="in_use">사용 중</option></select></label>
        <div className="toolbar"><button type="submit">저장</button><button type="button" onClick={() => {setForm(null); setEditing(null);}}>취소</button></div>
      </fieldset>
    </form>}
    <div className="filters"><label>장비 검색<input type="search" placeholder="이름, 관리번호, 사용자, 위치" value={query} onChange={event => setQuery(event.target.value)}/></label><label>상태 필터<select value={status} onChange={event => setStatus(event.target.value)}><option value="">전체 상태</option><option value="in_use">사용 중</option><option value="stored">보관 중</option></select></label></div>
    {loaded && <p>전체 {items.length}개 · 검색 결과 {visible.length}개</p>}
    <div className="table-wrap"><table><thead><tr>{['장비 이름','관리번호','사용하는 사람','위치','상태','작업'].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead><tbody>{visible.map(record => <tr key={record.id}><td>{record.payload.name}</td><td>{record.payload.number}</td><td>{record.payload.user || '—'}</td><td>{record.payload.location}</td><td><span className={`badge ${record.payload.status}`}>{record.payload.status === 'in_use' ? '사용 중' : '보관 중'}</span></td><td><button disabled={busy || !!uncertain} aria-label={`${record.payload.number} 수정`} onClick={() => {setEditing(record); setForm({...record.payload});}}>수정</button></td></tr>)}</tbody></table></div>
    {loaded && !visible.length && <p>{items.length ? '검색 결과가 없습니다.' : '아직 등록한 장비가 없습니다. 새 장비나 가짜 예시를 추가해 보세요.'}</p>}
  </section>;
}
