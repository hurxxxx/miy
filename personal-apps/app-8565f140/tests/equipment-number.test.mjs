import test from 'node:test';
import assert from 'node:assert/strict';
import {equipmentNumberError, normalizeEquipment, samples} from '../src/equipment.mjs';
test('number limit applies after trim and uppercase, using code points', () => {
  for (const raw of ['ß'.repeat(40), 'ß'.repeat(32)+'a', 'a'.repeat(65)]) {
    assert.equal(equipmentNumberError(raw), '관리번호는 대문자 변환 후 64자 이내여야 합니다.');
  }
  for (const raw of ['  '+ 'ß'.repeat(32) +'  ', 'a'.repeat(64), ' test-001 ', '😀'.repeat(64)]) {
    const input = {...samples[0], number: raw};
    const normalized = normalizeEquipment(input);
    assert.equal(equipmentNumberError(normalized.number), '');
    assert.equal(normalized.number, raw.trim().toUpperCase());
    assert.equal(input.number, raw);
  }
});
