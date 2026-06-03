import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('@/views/HomeView.vue')
    },
    {
      path: '/game/:characterId',
      name: 'game',
      component: () => import('@/views/GameView.vue'),
      props: true
    },
    {
      path: '/character/create',
      name: 'character-create',
      component: () => import('@/views/CharacterCreateView.vue')
    }
  ]
})

export default router
