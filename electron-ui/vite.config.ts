import {defineConfig} from 'vite';
export default defineConfig({base:'./',build:{rolldownOptions:{onwarn(warning,defaultHandler){if(warning.code==='MODULE_LEVEL_DIRECTIVE')return;defaultHandler(warning);}}}});
