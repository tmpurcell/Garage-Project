/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './templates/**/*.html',  // scan all HTML templates
    './static/js/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        // Automotive-inspired color palette
        'racing-red': '#DC2626',
        'racing-red-dark': '#991B1B',
        'racing-red-light': '#EF4444',
        
        'garage-gray': '#374151',
        'garage-gray-dark': '#1F2937',
        'garage-gray-light': '#6B7280',
        'garage-gray-lighter': '#9CA3AF',
        
        'engine-orange': '#EA580C',
        'engine-orange-dark': '#C2410C',
        'engine-orange-light': '#FB923C',
        
        'metallic-blue': '#1E40AF',
        'metallic-blue-dark': '#1E3A8A',
        'metallic-blue-light': '#3B82F6',
        
        'performance-green': '#059669',
        'performance-green-dark': '#047857',
        'performance-green-light': '#10B981',
        
        'chrome-silver': '#E5E7EB',
        'chrome-dark': '#9CA3AF',
        'carbon-black': '#111827',
        'carbon-gray': '#374151',
        
        'fuel-yellow': '#F59E0B',
        'fuel-yellow-dark': '#D97706',
        'fuel-yellow-light': '#FCD34D',
        
        'brake-red': '#DC2626',
        'brake-red-dark': '#B91C1C',
        'brake-red-light': '#F87171',
      },
    },
  },
  plugins: [],
}

