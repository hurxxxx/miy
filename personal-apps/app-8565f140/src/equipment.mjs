export const emptyEquipment = () => ({name: '', number: '', user: '', location: '', status: 'stored'});
export const samples = [
  {name: '노트북', number: 'TEST-001', user: '가상사용자 A', location: '가상 사무실', status: 'in_use'},
  {name: '모니터', number: 'TEST-002', user: '', location: '가상 창고', status: 'stored'},
];
export function filterEquipment(items, query, status) {
  const needle = query.trim().toLocaleLowerCase();
  return items.filter(({payload: p}) => (!status || p.status === status) &&
    [p.name, p.number, p.user, p.location].some(value => value.toLocaleLowerCase().includes(needle)));
}
export function normalizeEquipment(p) {
  return {...p, name: p.name.trim(), number: p.number.trim().toUpperCase(),
    location: p.location.trim(), user: p.status === 'stored' ? '' : p.user.trim()};
}

export function equipmentNumberError(number) {
  return [...number.trim().toUpperCase()].length > 64
    ? '관리번호는 대문자 변환 후 64자 이내여야 합니다.' : '';
}
