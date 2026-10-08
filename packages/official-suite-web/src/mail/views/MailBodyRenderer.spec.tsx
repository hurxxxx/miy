import { cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { MailBodyRenderer } from './MailBodyRenderer';
import {
  buildMailHtmlDocument,
  extractMailPreviewText,
} from './mail-html-document';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
afterEach(cleanup);

function parsed(html: string, allowRemoteImages = true) {
  const result = buildMailHtmlDocument(html, { allowRemoteImages });
  return {
    ...result,
    document: new DOMParser().parseFromString(result.srcDoc, 'text/html'),
  };
}

describe('existing Mail HTML policy', () => {
  it('removes active content, injected document policy, event handlers and unsafe links', () => {
    const { document } =
      parsed(`<script>bad()</script><iframe srcdoc="bad"></iframe>
      <meta http-equiv="refresh" content="0;url=https://remote.example"><base href="https://remote.example">
      <form><input value="secret"><button>Submit</button></form><style>@import 'https://remote.example'</style>
      <p onclick="bad()">Hello</p><a href="javascript:bad()">Bad link</a>
      <a href="https://safe.example">Safe link</a>`);
    expect(
      document.body.querySelector(
        'script,iframe,meta,base,form,input,button,style',
      ),
    ).toBeNull();
    expect(document.body.querySelector('[onclick],[srcdoc]')).toBeNull();
    const [bad, safe] = document.body.querySelectorAll('a');
    expect(bad?.hasAttribute('href')).toBe(false);
    expect(safe?.getAttribute('href')).toBe('https://safe.example');
    expect(safe?.getAttribute('rel')).toBe('noopener noreferrer');
    expect(safe?.getAttribute('target')).toBe('_blank');
    // This move preserves the existing renderer policy, without adding a CSP.
    expect(
      document.querySelector('meta[http-equiv="Content-Security-Policy"]'),
    ).toBeNull();
  });

  it('retains the current default remote images and strips alternate remote resource channels', () => {
    const { document, blockedRemoteImageCount } =
      parsed(`<p style="color:red; background:url(https://remote.example/bg)" background="https://remote.example/bg">Mail</p>
      <img src="https://remote.example/pixel" srcset="https://remote.example/large 2x" sizes="100vw">
      <img src="cid:part-1"><img src="data:image/png;base64,aGVsbG8=">`);
    expect(blockedRemoteImageCount).toBe(0);
    const images = document.body.querySelectorAll('img');
    expect(images[0]?.getAttribute('src')).toBe('https://remote.example/pixel');
    expect(images[0]?.hasAttribute('srcset')).toBe(false);
    expect(images[0]?.hasAttribute('sizes')).toBe(false);
    expect(images[1]?.getAttribute('src')).toBe('cid:part-1');
    expect(images[2]?.getAttribute('src')).toMatch(/^data:image/);
    expect(
      document.body.querySelector('p')?.getAttribute('style'),
    ).not.toContain('url');
    expect(document.body.querySelector('p')?.hasAttribute('background')).toBe(
      false,
    );
  });

  it('keeps the explicit image-blocking helper behavior', () => {
    const { document, blockedRemoteImageCount } = parsed(
      '<img src="https://remote.example/image"><img src="//remote.example/image"><img src="cid:part-1">',
      false,
    );
    expect(blockedRemoteImageCount).toBe(2);
    expect(document.body.querySelectorAll('img[src]')).toHaveLength(1);
    expect(
      document.body.querySelectorAll('img[aria-hidden="true"]'),
    ).toHaveLength(2);
  });

  it('uses the same iframe sandbox, no-referrer and remote-image default', () => {
    const { container } = render(
      <MailBodyRenderer
        body={{
          html_body: '<img src="https://remote.example/image">',
          text_body: '',
        }}
      />,
    );
    const iframe = container.querySelector('iframe');
    expect(iframe?.getAttribute('sandbox')).toBe(
      'allow-popups allow-popups-to-escape-sandbox',
    );
    expect(iframe?.getAttribute('referrerpolicy')).toBe('no-referrer');
    expect(iframe?.getAttribute('srcdoc')).toContain(
      'src="https://remote.example/image"',
    );
    expect(container.querySelector('button')).toBeNull();
  });

  it('renders plain text as text and sanitizes list preview content', () => {
    const { container } = render(
      <MailBodyRenderer
        body={{ html_body: '', text_body: '<img onerror="bad()">' }}
      />,
    );
    expect(container.querySelector('iframe,img')).toBeNull();
    expect(container.querySelector('pre')?.textContent).toBe(
      '<img onerror="bad()">',
    );
    expect(
      extractMailPreviewText(
        '<style>.hidden {color:red}</style><script>bad()</script><p>Hello&nbsp; team</p>',
      ),
    ).toBe('Hello team');
  });
});
