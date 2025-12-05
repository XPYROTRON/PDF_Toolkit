async function processFiles() {
    const progressBar = document.getElementById('progressBar');
    const progress = document.getElementById('progress');
    
    progressBar.classList.remove('hidden');
    processBtn.disabled = true;

    try {
        // Show initial progress
        progress.style.width = '30%';

        const formData = new FormData();
        
        // Add files - use 'file' for single file tools, 'files' for merge
        if (currentTool === 'merge') {
            uploadedFiles.forEach(file => {
                formData.append('files', file);
            });
        } else {
            // Single file tools
            formData.append('file', uploadedFiles[0]);
        }

        // Add tool-specific options
        const options = getToolOptions();
        for (const [key, value] of Object.entries(options)) {
            if (value) { // Only add if value exists
                formData.append(key, value);
            }
        }

        progress.style.width = '60%';

        const endpoint = getEndpoint();
        console.log('Sending request to:', endpoint);
        
        const response = await fetch(endpoint, {
            method: 'POST',
            body: formData
        });

        progress.style.width = '90%';

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || `Server error: ${response.status}`);
        }

        const blob = await response.blob();
        
        // Check if blob is valid
        if (blob.size === 0) {
            throw new Error('Received empty file from server');
        }

        // Create download link
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = getDownloadFilename();
        document.body.appendChild(a);
        a.click();
        
        // Cleanup
        setTimeout(() => {
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
        }, 100);

        progress.style.width = '100%';
        
        // Reset after successful processing
        setTimeout(() => {
            resetUploadArea();
            progressBar.classList.add('hidden');
        }, 2000);
        
    } catch (error) {
        console.error('Processing error:', error);
        alert('Error processing files: ' + error.message);
        progressBar.classList.add('hidden');
    } finally {
        processBtn.disabled = false;
    }
}

// Update the getEndpoint function to use the correct API routes
function getEndpoint() {
    const endpoints = {
        'merge': '/api/merge',
        'split': '/api/split',
        'compress': '/api/compress',
        'pdf-to-images': '/api/pdf-to-images',
        'protect': '/api/protect',
        'unlock': '/api/unlock'
    };
    return endpoints[currentTool];
}