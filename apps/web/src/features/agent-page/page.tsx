// #/agent — My agent. Top: the rig (your workspace │ conduit │ your agent). Below: connecting
// (one press, one command) until the agent shows up, then the full-width transmission stream.
import NumberFlow from '@number-flow/react';
import { Plug } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { onAgentEvent } from '../../shell/agent-bus';
import { Button } from '../../ui-kit';
import { ConnectPanel, connectionLabel } from './connect';
import type { AgentEvent } from './feed';
import { AccessUnconfirmed, canConnect, ensureAccess } from './grant';
import { type AgentPageProps, feedStore } from './index';
import { Rig } from './rig';
import { batchSentence, TransmissionStream } from './stream';
import { clientName } from './verbs';

const t = (lang: 'zh' | 'en', zh: string, en: string) => (lang === 'en' ? en : zh);

export function AgentPage(props: AgentPageProps) {
  const { lang, host, sessionKey } = props;
  const feed = useSyncExternalStore(feedStore.subscribe, feedStore.snapshot);
  const issued = useSyncExternalStore(
    (cb) => host?.subscribe(cb) ?? (() => {}),
    () => host?.issuedDelegation()?.delegationId ?? '',
  );
  const [connecting, setConnecting] = useState(false);
  const [failed, setFailed] = useState('');
  const [reveal, setReveal] = useState(false);
  const server = feed.connection.state;
  const phase =
    server === 'connected' ? 'connected' : server === 'idle' ? 'idle' : issued ? 'waiting' : 'none';
  const client = clientName(feed.connection.client);
  // The host learns what the server allows with its first workbench read.
  const hostReady = useSyncExternalStore(
    (cb) => host?.subscribe(cb) ?? (() => {}),
    () => (host ? host.snapshot().state !== 'unavailable' : true),
  );
  const allowed = useSyncExternalStore(
    (cb) => host?.subscribe(cb) ?? (() => {}),
    () => canConnect(host),
  );
  const ready = feed.loaded && hostReady;

  // Connected setup stays available as a compact summary; hand-backs take the focus.
  useEffect(() => {
    if (phase === 'connected') setReveal(false);
  }, [phase]);

  // While someone waits for the first connection, poll fast.
  useEffect(() => {
    feedStore.watch(phase === 'waiting');
    return () => feedStore.watch(false);
  }, [phase]);

  // Screen readers hear one merged sentence every 2 seconds, not every call.
  const [spoken, setSpoken] = useState('');
  const batch = useRef<AgentEvent[]>([]);
  useEffect(() => {
    const off = onAgentEvent((e) => batch.current.push(e));
    const id = setInterval(() => {
      if (!batch.current.length) return;
      setSpoken(batchSentence(batch.current, lang));
      batch.current = [];
    }, 2000);
    return () => {
      off();
      clearInterval(id);
    };
  }, [lang]);

  const secret = async () => {
    if (!host) return null;
    setFailed('');
    try {
      const token = (await ensureAccess(host))?.token ?? null;
      if (!token)
        setFailed(t(lang, '没能开通连接，请再试一次。', 'Access could not be issued. Try again.'));
      return token;
    } catch (error) {
      setFailed(
        error instanceof AccessUnconfirmed
          ? t(
              lang,
              '还没收到开通的结果。再按一次会核对原来的请求，不会多开一份。',
              'The answer did not arrive. Press again to check the original request; it will not open a second one.',
            )
          : t(lang, '没能开通连接，请再试一次。', 'Access could not be issued. Try again.'),
      );
      return null;
    }
  };
  const connect = async () => {
    setConnecting(true);
    const token = await secret();
    setConnecting(false);
    if (token) setReveal(true);
  };

  const works = useMemo(() => new Map(props.returned.map((w) => [w.id, w])), [props.returned]);
  const counts = useMemo(() => {
    let reads = 0;
    let backs = 0;
    let refused = 0;
    for (const e of feed.events) {
      if (e.tool === 'initialize') continue;
      if (e.status !== 'ok') refused++;
      else if (e.direction === 'to_agent') reads++;
      else backs++;
    }
    return { reads, backs, refused };
  }, [feed.events]);

  const showConnect = phase === 'waiting' || (reveal && phase !== 'none');
  const connectKey =
    phase === 'none' && (ready || !host) ? (
      <div className="ag-cta">
        <Button
          variant="primary"
          className="ag-connect-key"
          onClick={connect}
          disabled={!allowed}
          state={connecting ? 'loading' : 'idle'}
          icon={<Plug size={15} strokeWidth={1.7} />}
        >
          {t(lang, '连接你的 Agent', 'Connect your agent')}
        </Button>
        <p className="ag-cta-note">
          {allowed
            ? t(
                lang,
                '支持桌面 App 和命令行，复制后按步骤连接。',
                'Desktop apps and CLIs. Copy the setup and follow the steps.',
              )
            : t(
                lang,
                '这局练习不在服务器上运行，不能直连；可以用页底的任务包。',
                'This practice does not run on the server, so it cannot connect. Use the package below.',
              )}
        </p>
        {failed ? (
          <p className="ag-cta-error" role="alert">
            {failed}
          </p>
        ) : null}
      </div>
    ) : null;

  return (
    <div className="ag-root" data-lang={lang} data-connection={phase}>
      <header className="ag-head">
        <div className="ag-headline">
          <h1 id="ag-title" className="ag-title">
            {t(lang, '我的 Agent', 'My agent')}
          </h1>
          <span className="ag-head-status">
            <span className="rc-agent-light" data-state={phase} aria-hidden="true" />
            {phase === 'none'
              ? t(lang, '还没连接', 'Not connected')
              : connectionLabel(feed.connection, lang)}
          </span>
        </div>
        <p className="ag-lede">
          {props.hat === 'engineer'
            ? t(
                lang,
                '你自己的编码 Agent 经 MCP 接进这一局：能读工单、复现、试跑、起草签字单。签字只能你本人。',
                'Your own coding agent, connected to this practice over MCP. It can read the ticket, reproduce, run trials and draft the sign-off. Only you can sign.',
              )
            : t(
                lang,
                '你自己的编码 Agent 经 MCP 接进这一局：能读工作区、跑测试、交回草稿。采用和交付由你决定。',
                'Your own coding agent, connected to this practice over MCP. It reads the workspace, runs tests and hands back drafts. Adopting and submitting stay with you.',
              )}
        </p>
      </header>

      <Rig
        settled={feed.loaded}
        phase={phase}
        client={client}
        lastSeen={feed.connection.last_seen ?? undefined}
        workspace={props.workspace}
        lang={lang}
        caption={
          phase === 'waiting' ? (
            <span className="ag-shimmer">
              {t(lang, '等待你的 Agent…', 'Waiting for your agent…')}
            </span>
          ) : phase === 'idle' ? (
            <span>{t(lang, '用同一条命令可以重连', 'The same command reconnects it')}</span>
          ) : phase === 'connected' && !counts.reads && !counts.backs ? (
            <span>
              {t(lang, '已接通，等它第一次调用', 'Connected. Waiting for its first call')}
            </span>
          ) : null
        }
      >
        {connectKey ??
          (phase === 'connected' || phase === 'idle' ? (
            <dl className="ag-readouts" aria-label={t(lang, '读数', 'Readouts')}>
              <div>
                <dt>{t(lang, '读取', 'Reads')}</dt>
                <dd>
                  <NumberFlow value={counts.reads} />
                </dd>
              </div>
              <div>
                <dt>{t(lang, '交回与执行', 'Hand-backs & runs')}</dt>
                <dd>
                  <NumberFlow value={counts.backs} />
                </dd>
              </div>
              <div className={counts.refused ? 'is-bad' : ''}>
                <dt>{t(lang, '被拒', 'Refused')}</dt>
                <dd>
                  <NumberFlow value={counts.refused} />
                </dd>
              </div>
            </dl>
          ) : null)}
      </Rig>

      {(phase === 'connected' || phase === 'idle') && host ? (
        <div className="ag-connection-summary">
          <span className="ag-connect-status" role="status">
            <span className="rc-agent-light" data-state={phase} aria-hidden="true" />
            {connectionLabel(feed.connection, lang)}
          </span>
          <Button variant="ghost" onClick={() => setReveal(!reveal)} aria-expanded={showConnect}>
            {showConnect
              ? t(lang, '收起连接设置', 'Hide connection setup')
              : t(lang, '再看一次连接命令', 'Show the command again')}
          </Button>
        </div>
      ) : null}
      {showConnect && host ? (
        <ConnectPanel
          lang={lang}
          sessionId={sessionKey}
          origin={props.origin}
          opener={props.opener}
          secret={secret}
          connection={feed.connection}
        />
      ) : null}

      {phase !== 'none' ? (
        <section className="ag-transmission" aria-labelledby="ag-tx-title">
          <header className="ag-tx-head">
            <h2 id="ag-tx-title">{t(lang, '传输', 'Transmission')}</h2>
            <span className="ag-grow" />
          </header>
          <TransmissionStream
            events={feed.events}
            variant="full"
            spotlight
            lang={lang}
            liveFrom={feed.liveFrom}
            work={(id) => works.get(id) ?? null}
            onOpen={(e) => {
              if (e.object?.kind === 'work_product' && e.object.id) props.onReview(e.object.id);
            }}
            onAdopt={props.onAdopt}
            empty={
              <p>
                {phase === 'waiting'
                  ? t(
                      lang,
                      '连上以后，它的每一次调用都会在这里出现一行。',
                      'Once it connects, every call it makes appears here as a line.',
                    )
                  : t(lang, '还没有调用。对它说一句话试试。', 'No calls yet. Ask it something.')}
              </p>
            }
          />
        </section>
      ) : null}
      <p className="ag-sr" aria-live="polite">
        {spoken}
      </p>
    </div>
  );
}
