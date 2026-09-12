// Local visual/interaction fixture. No native commands, sessions or remote peers.
import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {JunctionPanel} from '../../src/components/junction/JunctionPanel';
import {junctionState} from '../../src/services/junction/state';
import '../../src/App.css';
import '../../src/index.css';
const states = ['invite_ready', 'approval_pending', 'connected', 'interrupted', 'needs_exchange', 'failed', 'response_ready'];
function Fixture() {
  const [host, setHost] = useState(true), [state, setState] = useState('invite_ready'), [attempt, setAttempt] = useState(1);
  React.useEffect(() => {
    const exchange = {state, inviteId: `attempt-${attempt}`, waitingFor: 'none', ...(host ? {inviteText: `PLUMDECK-JUNCTION-test-invite-${attempt}`} : {})};
    junctionState.set({active: true, sessionId: 'fixture', sessionName: 'Friday Session', revision: attempt, epoch: '1', localPeerId: host ? 'host' : 'guest', hostPeerId: 'host', performerPeerId: '', lifecycle: 'lobby', handoffState: 'IDLE', participants: [
      {peerId: 'host', djName: 'DJ YUTA', displayName: 'DJ YUTA', approved: true, isHost: true, orderIndex: 0, ...(host ? {} : {exchange})},
      {peerId: 'guest', djName: 'DJ MIKA', displayName: 'DJ MIKA', approved: state === 'connected', orderIndex: 1, ...(host ? {exchange} : {})},
    ], readiness: {ready: false, reasons: []}, program: {state: 'idle'}, connection: {state: state === 'connected' ? 'connected' : 'pending'}, exchange: {mode: 'manual', state, inviteId: `attempt-${attempt}`, responseText: `PLUMDECK-JUNCTION-test-answer-${attempt}`}} as never);
  }, [host, state, attempt]);
  return <><aside style={{position:'fixed',left:20,top:20,color:'white',display:'grid',gap:15}}>
    <h1>Junction UI check</h1><label>表示する側<select aria-label="表示する側" value={host ? 'host' : 'guest'} onChange={(e) => {setHost(e.target.value === 'host');setState(e.target.value === 'host' ? 'invite_ready' : 'response_ready');}}><option value="host">管理DJ</option><option value="guest">参加DJ</option></select></label>
    <label>接続状態<select aria-label="接続状態" value={state} onChange={(e) => setState(e.target.value)}>{states.map(s => <option key={s}>{s}</option>)}</select></label>
    <button onClick={() => {setAttempt(a => a + 1);setState(host ? 'invite_ready' : 'response_ready');}}>新しい招待の状態にする</button>
    <p>テスト用データです。相手への送信・接続は行いません。</p>
  </aside><JunctionPanel open onClose={() => {}} incomingInvite={null} onConsumeIncoming={() => {}} /></>;
}
createRoot(document.getElementById('root')!).render(<Fixture/>);
