/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      // 自定义滚动条样式
      scrollbar: ['rounded'],
    },
  },
  plugins: [
    require('@tailwindcss/typography'), // 用于 AI 消息的 Markdown 渲染
  ],
}
