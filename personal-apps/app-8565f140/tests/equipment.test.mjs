import test from 'node:test';
import assert from 'node:assert/strict';
import {samples, filterEquipment, normalizeEquipment} from '../src/equipment.mjs';
test('search covers all four fields and combines status', () => {
 const items = samples.map(payload => ({payload}));
 for (const query of ['노트북', 'test-001', '가상사용자 A', '가상 사무실']) assert.equal(filterEquipment(items, query, '').length, 1);
 assert.equal(filterEquipment(items, '노트북', 'stored').length, 0);
 assert.equal(filterEquipment(items, '', '').length, 2);
 assert.equal(filterEquipment(items, '없는 장비', '').length, 0);
});
test('stored equipment clears user and canonicalizes management number', () => {
 assert.deepEqual(normalizeEquipment({...samples[0], number:' test-001 ', status:'stored'}), {...samples[0], number:'TEST-001', status:'stored', user:''});
});
