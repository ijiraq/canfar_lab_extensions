import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { Dialog, showDialog } from '@jupyterlab/apputils';
import { IDocumentManager } from '@jupyterlab/docmanager';
import { IMainMenu } from '@jupyterlab/mainmenu';
import { Menu } from '@lumino/widgets';

import { canfarRequest } from './request';

interface ITutorialsEntry {
  menu_name: string;
  action: string;
  disposition: string;
  parent: string;
  src: string;
  dest: string;
}

interface ITutorialsHierarchy {
  entries: { [name: string]: ITutorialsEntry } | null;
  subhierarchies: { [name: string]: ITutorialsHierarchy } | null;
}

async function fetchHierarchy(): Promise<ITutorialsHierarchy> {
  const response = await canfarRequest('tutorials', { method: 'GET' });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Tutorials GET failed (${response.status})`);
  }
  return data as ITutorialsHierarchy;
}

async function openTutorial(
  docManager: IDocumentManager,
  entry: ITutorialsEntry,
  disposition: string = entry.disposition
): Promise<void> {
  const body = { ...entry, disposition };
  const response = await canfarRequest('tutorials', {
    method: 'POST',
    body: JSON.stringify(body)
  });

  if (response.status === 409) {
    const result = await showDialog({
      title: 'Target file exists',
      body: `Overwrite file "${entry.dest}"?`,
      buttons: [Dialog.cancelButton(), Dialog.okButton({ label: 'OVERWRITE' })]
    });
    if (result.button?.label === 'OVERWRITE') {
      await openTutorial(docManager, entry, 'overwrite');
    }
    return;
  }

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || `Tutorials POST failed (${response.status})`);
  }

  const data = await response.json();
  const dest = data.dest || entry.dest;
  docManager.openOrReveal(dest);
}

function buildMenu(
  app: JupyterFrontEnd,
  docManager: IDocumentManager,
  name: string,
  hierarchy: ITutorialsHierarchy,
  parentMenu: Menu | null
): void {
  let menu = parentMenu;
  if (menu === null) {
    menu = new Menu({ commands: app.commands });
    menu.title.label = 'Tutorials';
  }

  if (hierarchy.subhierarchies) {
    for (const subh of Object.keys(hierarchy.subhierarchies)) {
      const sObj = hierarchy.subhierarchies[subh];
      if (!sObj || (!sObj.entries && !sObj.subhierarchies)) {
        continue;
      }
      const smenu = new Menu({ commands: app.commands });
      smenu.title.label = subh;
      menu.addItem({ submenu: smenu, type: 'submenu' });
      buildMenu(app, docManager, subh, sObj, smenu);
    }
  }

  if (hierarchy.entries) {
    menu.addItem({ type: 'separator' });
    for (const entryName of Object.keys(hierarchy.entries)) {
      const entry = hierarchy.entries[entryName];
      const cmdId = `canfar-tutorials:${entry.parent}/${entry.menu_name}`;
      if (!app.commands.hasCommand(cmdId)) {
        app.commands.addCommand(cmdId, {
          label: entryName,
          execute: async () => {
            try {
              await openTutorial(docManager, entry);
            } catch (err) {
              const msg = err instanceof Error ? err.message : String(err);
              await showDialog({
                title: 'Tutorials',
                body: msg,
                buttons: [Dialog.okButton()]
              });
            }
          }
        });
      }
      menu.addItem({ command: cmdId, type: 'command' });
    }
  }
}

export const tutorialsPlugin: JupyterFrontEndPlugin<void> = {
  id: 'canfar_lab_extensions:tutorials',
  description: 'CANFAR Tutorials menu',
  autoStart: true,
  requires: [IMainMenu, IDocumentManager],
  activate: (
    app: JupyterFrontEnd,
    mainMenu: IMainMenu,
    docManager: IDocumentManager
  ) => {
    void (async () => {
      try {
        const hierarchy = await fetchHierarchy();
        const tutorialsMenu = new Menu({ commands: app.commands });
        tutorialsMenu.title.label = 'Tutorials';
        buildMenu(app, docManager, 'root', hierarchy, tutorialsMenu);
        mainMenu.addMenu(tutorialsMenu);
      } catch (err) {
        console.error('canfar_lab_extensions: failed to load Tutorials menu', err);
      }
    })();
  }
};
