import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { ICommandPalette } from '@jupyterlab/apputils';
import { ILauncher } from '@jupyterlab/launcher';
import { LabIcon } from '@jupyterlab/ui-components';
import { Widget } from '@lumino/widgets';
import { initFirefly } from 'firefly-api-access';
import { set } from 'lodash';

import { canfarRequest } from './request';

const COMMAND_ID = 'canfar:open-firefly-viewer';
const TAB_ID = 'canfar-firefly-viewer-tab';
const CATEGORY = 'Firefly';
const LABEL = 'Firefly Viewer';
const POLL_MS = 3000;
// Body class: styles the launcher card, which has no notion of "disabled".
const STARTING_CLASS = 'canfar-firefly-starting';

interface IFireflyStatus {
  status: 'idle' | 'starting' | 'ready' | 'error';
  message: string;
  elapsed?: number;
  fireflyURL?: string;
  fireflyChannel?: string;
  fireflyHtmlFile?: string;
  help?: string;
  helpURL?: string;
}

const fireflyIconSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <circle cx="12" cy="12" r="10" fill="#1a73e8"/>
  <text x="12" y="16" text-anchor="middle" font-size="10" fill="white" font-family="sans-serif">FF</text>
</svg>`;

async function fireflyRequest(method: 'GET' | 'POST'): Promise<IFireflyStatus> {
  const response = await canfarRequest('firefly/ensure', { method });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || data.error || `Firefly request failed (${response.status})`);
  }
  return data as IFireflyStatus;
}

async function loadFireflyApi(url: string, channel: string): Promise<any> {
  const w = window as any;
  if (!w.firefly?.initialized) {
    w.firefly = { ...w.firefly, wsch: channel };
  }
  if (!w.getFireflyAPI) {
    w.getFireflyAPI = initFirefly(url);
    w.canfarFireflyURL = url;
  }
  try {
    return await w.getFireflyAPI();
  } catch (err) {
    // initFirefly caches a failed load forever; allow Retry to load again.
    w.getFireflyAPI = undefined;
    w.canfarFireflyURL = undefined;
    throw err;
  }
}

/** URL this page loaded the Firefly JS API from; it cannot be swapped without a reload. */
function loadedFireflyURL(): string | undefined {
  return (window as any).canfarFireflyURL;
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${String(s).padStart(2, '0')}s` : `${s}s`;
}

function el(tag: string, className: string, text?: string): HTMLElement {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) {
    node.textContent = text;
  }
  return node;
}

class FireflyRootWidget extends Widget {
  private controlApp: any;
  private viewerURL: string | undefined;
  private _launching = false;

  constructor(
    id: string,
    icon: LabIcon,
    private readonly onLaunchingChanged: () => void
  ) {
    super({ node: el('div', 'canfar-firefly-root') });
    this.id = id;
    this.title.icon = icon;
    this.title.label = LABEL;
    this.title.closable = true;
    this.node.tabIndex = -1;
    this.node.style.outline = 'none';
  }

  get launching(): boolean {
    return this._launching;
  }

  /**
   * Start, retry, or re-check the launch. With the viewer up this only asks
   * the server to re-probe Firefly, which relaunches it if the session was
   * deleted outside Lab (e.g. from the Science Portal).
   */
  launch(): void {
    if (this._launching) {
      return;
    }
    void this.run();
  }

  private setLaunching(value: boolean): void {
    this._launching = value;
    this.title.label = value ? `${LABEL} (starting…)` : LABEL;
    this.title.className = value ? 'canfar-firefly-tab-starting' : '';
    document.body.classList.toggle(STARTING_CLASS, value);
    this.onLaunchingChanged();
  }

  private async run(): Promise<void> {
    this.setLaunching(true);
    if (!this.controlApp) {
      this.showStatus('Contacting CANFAR…');
    }
    try {
      let state = await fireflyRequest('POST');
      if (this.isDisposed) {
        return;
      }
      if (state.status === 'ready' && this.controlApp && state.fireflyURL === this.viewerURL) {
        return;
      }
      while (state.status === 'starting') {
        this.showStatus(state.message, state.elapsed);
        await new Promise(resolve => setTimeout(resolve, POLL_MS));
        if (this.isDisposed) {
          return;
        }
        state = await fireflyRequest('GET');
      }
      if (state.status === 'error') {
        this.showError(state.message, state.help, state.helpURL);
        return;
      }
      if (state.status !== 'ready' || !state.fireflyURL || !state.fireflyChannel) {
        throw new Error(state.message || 'Firefly did not start');
      }
      const loaded = loadedFireflyURL();
      if (loaded && loaded !== state.fireflyURL) {
        this.showReload();
        return;
      }
      this.showStatus('Firefly is up; loading the viewer…');
      const firefly = await loadFireflyApi(state.fireflyURL, state.fireflyChannel);
      if (this.isDisposed) {
        return;
      }
      this.setContent();
      this.startViewer(firefly, state.fireflyURL, state.fireflyHtmlFile);
      this.viewerURL = state.fireflyURL;
    } catch (err) {
      if (!this.isDisposed) {
        this.showError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      if (!this.isDisposed) {
        this.setLaunching(false);
      }
    }
  }

  private showStatus(message: string, elapsed?: number): void {
    const box = el('div', 'canfar-firefly-status');
    box.append(
      el('div', 'canfar-firefly-spinner'),
      el('h2', 'canfar-firefly-status-title', 'Starting Firefly on CANFAR'),
      el('p', 'canfar-firefly-status-message', message)
    );
    if (elapsed !== undefined) {
      box.append(el('p', 'canfar-firefly-status-elapsed', `Elapsed: ${formatElapsed(elapsed)}`));
    }
    box.append(
      el(
        'p',
        'canfar-firefly-status-hint',
        'Starting a new Firefly session can take several minutes. You can keep ' +
          'working in other tabs; the viewer will appear here when it is ready.'
      )
    );
    this.setContent(box);
  }

  private showError(message: string, help?: string, helpURL?: string): void {
    const box = el('div', 'canfar-firefly-status canfar-firefly-error');
    box.append(
      el('h2', 'canfar-firefly-status-title', 'Firefly could not start'),
      el('p', 'canfar-firefly-status-message', message)
    );
    if (help) {
      box.append(el('p', 'canfar-firefly-status-help', help));
    }
    const actions = el('div', 'canfar-firefly-status-actions');
    const retry = el('button', 'jp-Button jp-mod-styled jp-mod-accept', 'Retry') as HTMLButtonElement;
    retry.onclick = () => this.launch();
    actions.append(retry);
    if (helpURL) {
      const portal = el('a', 'jp-Button jp-mod-styled jp-mod-reject', 'Open Science Portal') as HTMLAnchorElement;
      portal.href = helpURL;
      portal.target = '_blank';
      portal.rel = 'noopener noreferrer';
      actions.append(portal);
    }
    box.append(actions);
    this.setContent(box);
  }

  private showReload(): void {
    const box = el('div', 'canfar-firefly-status');
    const reload = el('button', 'jp-Button jp-mod-styled jp-mod-accept', 'Reload page') as HTMLButtonElement;
    reload.onclick = () => window.location.reload();
    box.append(
      el('h2', 'canfar-firefly-status-title', 'Firefly restarted at a new address'),
      el(
        'p',
        'canfar-firefly-status-message',
        'This page is still attached to the previous Firefly session, which is gone. ' +
          'Save your notebooks, then reload the page to connect the viewer to the ' +
          'new session. Running kernels are not affected.'
      ),
      reload
    );
    this.setContent(box);
  }

  /** Replace the tab contents, tearing down a rendered viewer first. */
  private setContent(content?: HTMLElement): void {
    if (this.controlApp) {
      this.controlApp.unrender();
      this.controlApp = undefined;
      this.viewerURL = undefined;
    }
    this.node.replaceChildren(...(content ? [content] : []));
  }

  private startViewer(firefly: any, fireflyURL: string, fireflyHtmlFile?: string): void {
    const { util, action } = firefly;
    const props: any = {
      div: this.id,
      renderTreeId: this.id,
      template: fireflyHtmlFile === 'slate.html' ? 'FireflySlate' : 'FireflyViewer',
      disableDefaultDropDown: true
    };
    const fallbackMenu = [
      { label: 'Images', action: 'ImageSelectDropDownSlateCmd' },
      { label: 'TAP Searches', action: 'TAPSearch' },
      { label: 'Catalogs', action: 'IrsaCatalogDropDown' },
      { label: 'Charts', action: 'ChartSelectDropDownCmd' },
      { label: 'Upload', action: 'FileUploadDropDownCmd' }
    ];
    if (!firefly.originalAppProps) {
      props.menu = fallbackMenu;
    }
    if (fireflyURL.endsWith('irsaviewer')) {
      set(props, 'slotProps.banner.slotProps.tabs.pl', 0);
      set(props, 'slotProps.banner.slotProps.icon.style.marginTop', 0);
    }
    action.dispatchApiToolsView(true);
    this.controlApp = util.startAsAppFromApi(this.id, props);
  }

  dispose(): void {
    if (this.isDisposed) {
      return;
    }
    if (this._launching) {
      document.body.classList.remove(STARTING_CLASS);
    }
    if (this.controlApp) {
      this.controlApp.unrender();
    }
    this.controlApp = undefined;
    super.dispose();
    this.onLaunchingChanged();
  }
}

export const fireflyPlugin: JupyterFrontEndPlugin<void> = {
  id: 'canfar_lab_extensions:firefly',
  description: 'CANFAR Firefly Viewer launcher',
  autoStart: true,
  requires: [ICommandPalette],
  optional: [ILauncher],
  activate: (
    app: JupyterFrontEnd,
    palette: ICommandPalette,
    launcher: ILauncher | null
  ) => {
    const icon = new LabIcon({
      name: 'canfar_lab_extensions:firefly-icon',
      svgstr: fireflyIconSvg
    });
    let widget: FireflyRootWidget | undefined;
    const launching = () => !!widget && !widget.isDisposed && widget.launching;

    app.commands.addCommand(COMMAND_ID, {
      label: () => (launching() ? `${LABEL} (starting…)` : LABEL),
      caption: 'Launch Firefly on CANFAR and open it in JupyterLab',
      icon,
      // Greys the item in menus/palette; the launcher card ignores this and
      // just focuses the existing tab.
      isEnabled: () => !launching(),
      execute: () => {
        if (!widget || widget.isDisposed) {
          widget = new FireflyRootWidget(TAB_ID, icon, () =>
            app.commands.notifyCommandChanged(COMMAND_ID)
          );
          app.shell.add(widget, 'main');
        }
        app.shell.activateById(widget.id);
        widget.launch();
        return widget;
      }
    });

    palette.addItem({ command: COMMAND_ID, category: CATEGORY });
    if (launcher) {
      launcher.add({ command: COMMAND_ID, category: CATEGORY, rank: 1 });
    }
  }
};
