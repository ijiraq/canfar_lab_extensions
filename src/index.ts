import { JupyterFrontEndPlugin } from '@jupyterlab/application';

import { fireflyPlugin } from './firefly';
import { tutorialsPlugin } from './tutorials';

import '../style/index.js';

const plugins: JupyterFrontEndPlugin<void>[] = [fireflyPlugin, tutorialsPlugin];

export default plugins;
