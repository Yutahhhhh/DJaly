{
  find . -type f \( -name "*.tsx" -o -name "*.ts" \) \
  -not -path "*/node_modules/*" \
  -not -path "*/backend/*" \
  -not -path "*/.wrangler/*" \
  -not -path "*/dist/*" \
  -not -path "*/venv/*" \
  -not -path "*/.cache/*" \
  -not -path "*/.git/*" \
  -not -path "*/temp/*" \
  -not -path "*/.venv/*" \
  -not -path "*/.pnpm-store/*" \
  -not -path "*/.astro/*" \
  -not -path "*.d.ts" \
  | sort | while read file; do
    echo "## $file"
    echo
    cat "$file"
    echo
  done
} > output.txt