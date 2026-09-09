import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, BookOpen, ChevronDown, Search, ZoomIn } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { docGroups, docTopics, type DocTopic } from './topics';
import './docs.css';

export function DocsView() {
  const [query, setQuery] = useState('');
  const [topicId, setTopicId] = useState<string | null>(() => {
    const saved = sessionStorage.getItem('djaly.docs.topic');
    return docTopics.some(topic => topic.id === saved) ? saved : null;
  });
  const [zoom, setZoom] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const topic = docTopics.find(item => item.id === topicId);
  const results = useMemo(() => {
    const words = query.normalize('NFKC').toLocaleLowerCase('ja').trim().split(/\s+/).filter(Boolean);
    return docTopics.filter(item => {
      const text = [item.title, item.summary, item.location, item.group, ...item.steps, ...item.details.flatMap(detail => [detail.title, ...detail.body])].join(' ').normalize('NFKC').toLocaleLowerCase('ja');
      return words.every(word => text.includes(word));
    });
  }, [query]);
  const navigate = (id: string | null) => { setTopicId(id); setQuery(''); setZoom(false); };
  useEffect(() => {
    if (topicId) sessionStorage.setItem('djaly.docs.topic', topicId);
    else sessionStorage.removeItem('djaly.docs.topic');
    scroller.current?.scrollTo({ top: 0 });
    heading.current?.focus({ preventScroll: true });
  }, [topicId]);
  const card = (item: DocTopic) => <button key={item.id} className="docs-card" onClick={() => navigate(item.id)}>
    <span className="docs-card-title">{item.title}<ArrowRight aria-hidden="true" size={16}/></span>
    <span>{item.summary}</span>
  </button>;
  return <div className="docs-view" ref={scroller}>
    <header className="docs-header">
      <button className="docs-home" onClick={() => navigate(null)} aria-label="Docsのトピック一覧"><BookOpen size={20} aria-hidden="true"/><span>Docs</span></button>
      <label className="docs-search"><Search size={17} aria-hidden="true"/><input aria-label="ドキュメントを検索" type="search" placeholder="操作や機能を検索…" value={query} onChange={event => setQuery(event.target.value)}/></label>
    </header>
    <div className="docs-content">
      {query.trim() ? <>
        <h1 ref={heading} tabIndex={-1}>検索結果</h1><p className="docs-lead" role="status">{results.length}件のトピック</p>
        {results.length ? <div className="docs-grid">{results.map(card)}</div> : <div className="docs-empty"><p>見つかりませんでした。短い言葉や、画面のボタン名で検索してみてください。</p><button className="docs-link" onClick={() => setQuery('')}>検索を解除</button></div>}
      </> : topic ? <article key={topic.id}>
        <button className="docs-back" onClick={() => navigate(null)}><ArrowLeft size={16} aria-hidden="true"/>トピック一覧</button>
        <p className="docs-eyebrow">{topic.group}</p><h1 ref={heading} tabIndex={-1}>{topic.title}</h1><p className="docs-lead">{topic.summary}</p>
        <p className="docs-location"><span>開く場所</span>{topic.location}</p>
        <figure className="docs-figure"><button onClick={() => setZoom(true)} aria-label={`${topic.title}の画面を拡大`}><img src={`/docs/${topic.image}.png`} alt={topic.caption} loading="lazy"/><span className="docs-zoom"><ZoomIn size={15} aria-hidden="true"/>拡大</span></button><figcaption>{topic.caption}<span>説明用データを表示した画面です。</span></figcaption></figure>
        <section aria-label="基本の手順"><h2>基本の手順</h2><ol className="docs-steps">{topic.steps.map((step, index) => <li key={step}><span aria-hidden="true">{index + 1}</span><p>{step}</p></li>)}</ol></section>
        <section className="docs-details" aria-label="詳しい使い方"><h2>もう少し詳しく</h2>{topic.details.map(detail => <details key={detail.title}><summary>{detail.title}<ChevronDown size={16} aria-hidden="true"/></summary><div>{detail.body.map(body => <p key={body}>{body}</p>)}</div></details>)}</section>
        <nav aria-label="関連トピック" className="docs-related"><h2>あわせて読む</h2><div className="docs-grid">{docTopics.filter(item => topic.related.includes(item.id)).map(card)}</div></nav>
        <Dialog open={zoom} onOpenChange={setZoom}><DialogContent className="docs-image-dialog"><DialogTitle>{topic.title}</DialogTitle><DialogDescription>{topic.caption} 説明用データを表示しています。</DialogDescription><div><img src={`/docs/${topic.image}.png`} alt={topic.caption}/></div></DialogContent></Dialog>
      </article> : <>
        <p className="docs-eyebrow">DJALY GUIDE</p><h1 ref={heading} tabIndex={-1}>やりたいことから、探す。</h1><p className="docs-lead">楽曲の整理からDJプレイ、Junctionでの交代まで。<br/>必要な操作を、画面と手順で確認できます。</p>
        <div className="docs-start"><BookOpen aria-hidden="true" size={24}/><div><strong>初めて使う方へ</strong><p>取り込みからプレイまでの流れを確認しましょう。</p></div><button className="docs-link" onClick={() => navigate('start')}>はじめる<ArrowRight size={16} aria-hidden="true"/></button></div>
        <nav className="docs-categories" aria-label="トピックの分類">{docGroups.map((group, index) => <a key={group} href={`#docs-group-${index}`}>{group}</a>)}</nav>
        {docGroups.map((group, index) => <section className="docs-group" id={`docs-group-${index}`} key={group}><h2>{group}</h2><div className="docs-grid">{docTopics.filter(item => item.group === group).map(card)}</div></section>)}
      </>}
    </div>
  </div>;
}
