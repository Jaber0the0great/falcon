const fs = require('fs');
const path = require('path');
const esbuild = require('esbuild');

// 1. Create static/dist/js and static/dist/css directories
const distJsDir = path.resolve(__dirname, 'static/dist/js');
const distCssDir = path.resolve(__dirname, 'static/dist/css');

fs.mkdirSync(distJsDir, { recursive: true });
fs.mkdirSync(distCssDir, { recursive: true });

console.log('Concatenating JS files...');
// Read files in order
const jsFiles = [
    'static/js/socket.js',
    'static/js/webrtc.js',
    'static/js/app.js',
    'static/js/settings.js'
];

let jsContent = '';
jsFiles.forEach(file => {
    jsContent += fs.readFileSync(path.resolve(__dirname, file), 'utf8') + '\n;';
});

// Write concatenated temp file
const tempJsPath = path.resolve(__dirname, 'static/js/temp_bundle.js');
fs.writeFileSync(tempJsPath, jsContent, 'utf8');

console.log('Minifying JS bundle...');
esbuild.buildSync({
    entryPoints: [tempJsPath],
    outfile: path.resolve(distJsDir, 'bundle.min.js'),
    minify: true,
    bundle: false,
});

// Clean up temp file
if (fs.existsSync(tempJsPath)) {
    fs.unlinkSync(tempJsPath);
}

console.log('Minifying csrf.js...');
esbuild.buildSync({
    entryPoints: [path.resolve(__dirname, 'static/js/csrf.js')],
    outfile: path.resolve(distJsDir, 'csrf.min.js'),
    minify: true,
});

console.log('Minifying style.css...');
esbuild.buildSync({
    entryPoints: [path.resolve(__dirname, 'static/css/style.css')],
    outfile: path.resolve(distCssDir, 'style.min.css'),
    minify: true,
});

console.log('Build completed successfully!');
