import { createPinia } from 'pinia'
import { createApp } from 'vue'

import WorkbenchApp from './WorkbenchApp.vue'
import '@unocss/reset/tailwind.css'
import 'virtual:uno.css'
import './styles/global.css'
import './styles/sector-tones.css'

createApp(WorkbenchApp).use(createPinia()).mount('#app')
