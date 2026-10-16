import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { ICommandPalette, showDialog, Dialog } from '@jupyterlab/apputils';
import { ILauncher } from '@jupyterlab/launcher';
import { LabIcon } from '@jupyterlab/ui-components';
import { Widget } from '@lumino/widgets';
import { initFirefly } from 'firefly-api-access';
import { set } from 'lodash';

import { canfarRequest } from './request';

const COMMAND_ID = 'canfar:open-firefly-viewer';
const TAB_ID = 'canfar-firefly-viewer-tab';
const CATEGORY = 'Firefly';

interface IFireflyConfig {
  fireflyURL: string;
  fireflyChannel: string;
  fireflyHtmlFile?: string;
}

let widgetId: string | undefined;

const fireflyIconSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <circle cx="12" cy="12" r="10" fill="#1a73e8"/>
  <text x="12" y="16" text-anchor="middle" font-size="10" fill="white" font-family="sans-serif">FF</text>
</svg>`;

async function ensureFirefly(): Promise<IFireflyConfig> {
  const response = await canfarRequest('firefly/ensure', { method: 'POST' });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Firefly ensure failed (${response.status})`);
  }
  if (!data.fireflyURL) {
    throw new Error('Firefly ensure returned no fireflyURL');
  }
  return data as IFireflyConfig;
}

async function loadFireflyApi(cfg: IFireflyConfig): Promise<any> {
  const { fireflyURL, fireflyChannel: channel } = cfg;
  const w = window as any;
  if (!w.firefly?.initialized) {
    w.firefly = { ...w.firefly, wsch: channel };
  }
  if (!w.getFireflyAPI) {
    w.getFireflyAPI = initFirefly(fireflyURL);
  }
  return w.getFireflyAPI();
}

class FireflyRootWidget extends Widget {
  private controlApp: any;

  constructor(
    id: string,
    private readonly cfg: IFireflyConfig
  ) {
    super({ node: FireflyRootWidget.createNode(id) });
    this.id = id;
    this.title.label = 'Firefly Viewer';
    this.title.closable = true;
    this.node.tabIndex = -1;
    this.node.style.outline = 'none';
    void this.start();
  }

  private static createNode(id: string): HTMLElement {
    const node = document.createElement('div');
    node.id = id;
    node.className = 'canfar-firefly-root';
    const tmp = document.createElement('div');
    tmp.className = 'canfar-firefly-loading';
    tmp.textContent = 'Firefly Loading...';
    node.appendChild(tmp);
    return node;
  }

  private async start(): Promise<void> {
    try {
      const firefly = await loadFireflyApi(this.cfg);
      this.startViewer(firefly, this.id, this.cfg.fireflyURL, this.cfg.fireflyHtmlFile);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      this.node.innerHTML = `<div class="canfar-firefly-loading">Firefly failed to load: ${msg}</div>`;
    }
  }

  private startViewer(
    firefly: any,
    id: string,
    fireflyURL: string,
    fireflyHtmlFile?: string
  ): void {
    const { util, action } = firefly;
    const props: any = {
      div: id,
      renderTreeId: id,
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
    this.controlApp = util.startAsAppFromApi(id, props);
  }

  dispose(): void {
    widgetId = undefined;
    if (this.controlApp) {
      this.controlApp.unrender();
    }
    this.controlApp = undefined;
    super.dispose();
  }
}

async function openFirefly(app: JupyterFrontEnd): Promise<void> {
  try {
    const cfg = await ensureFirefly();
    if (!widgetId) {
      const widget = new FireflyRootWidget(TAB_ID, cfg);
      widgetId = widget.id;
      if (app.shell.add) {
        app.shell.add(widget, 'main');
      } else {
        throw new Error('Could not add Firefly to the Lab shell');
      }
    }
    app.shell.activateById(widgetId);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    await showDialog({
      title: 'Firefly',
      body: msg,
      buttons: [Dialog.okButton()]
    });
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

    app.commands.addCommand(COMMAND_ID, {
      label: 'Firefly Viewer',
      caption: 'Launch Firefly on CANFAR and open it in JupyterLab',
      icon,
      execute: () => openFirefly(app)
    });

    palette.addItem({ command: COMMAND_ID, category: CATEGORY });
    if (launcher) {
      launcher.add({ command: COMMAND_ID, category: CATEGORY, rank: 1 });
    }
  }
};
