function result = scanCodebaseCoverage(codebaseDir, callSequence, functionTable)
% SCANCODBASECOVERAGE Compare profiler call data against a codebase directory.
%
%   result = scanCodebaseCoverage(codebaseDir, callSequence, functionTable)
%
%   Inputs:
%     codebaseDir   - Root directory of the codebase to scan
%     callSequence  - struct array from parseProfilerPhases (can be empty [])
%     functionTable - FunctionTable from the profiler data
%
%   Output:
%     result - struct with fields:
%       .codebaseFunctions - cell array of all .m function names found
%       .codebaseFiles     - cell array of full file paths
%       .calledFunctions   - cell array of functions that appear in the profiler data
%       .uncalledFunctions - cell array of functions not found in profiler data
%       .uncalledFiles     - cell array of file paths for uncalled functions
%       .coveragePercent   - percentage of codebase functions that were called
%       .coverageTable     - table with columns: Name, File, Called, CallCount

    if ~isfolder(codebaseDir)
        error('scanCodebaseCoverage:badDir', ...
            'Directory does not exist: %s', codebaseDir);
    end

    % Scan for all .m files (top-level functions only)
    mFiles = dir(fullfile(codebaseDir, '**', '*.m'));

    % Filter to actual files (not directories)
    mFiles = mFiles(~[mFiles.isdir]);

    nFiles = numel(mFiles);
    codebaseFuncs = cell(nFiles, 1);
    codebaseFiles = cell(nFiles, 1);

    for k = 1:nFiles
        [~, fname, ~] = fileparts(mFiles(k).name);
        codebaseFuncs{k} = fname;
        codebaseFiles{k} = fullfile(mFiles(k).folder, mFiles(k).name);
    end

    % Build the set of functions that appear in profiler data
    % Use both FunctionTable (all profiled functions) and callSequence (phase-specific)
    profilerFuncNames = {};

    % From FunctionTable: extract base function names
    if ~isempty(functionTable)
        for k = 1:numel(functionTable)
            rawName = functionTable(k).FunctionName;
            % FunctionName may be like 'path>funcName' or 'funcName'
            parts = strsplit(rawName, '>');
            baseName = parts{end};
            % Strip any subfunc markers
            dotParts = strsplit(baseName, '.');
            baseName = dotParts{1};
            profilerFuncNames{end+1} = baseName; %#ok<AGROW>
        end
    end

    % From callSequence: extract function names for phase-specific coverage
    phaseCalledNames = {};
    phaseCallCounts = containers.Map();
    if ~isempty(callSequence)
        for k = 1:numel(callSequence)
            if strcmp(callSequence(k).event, 'enter')
                rawName = callSequence(k).funcName;
                parts = strsplit(rawName, '>');
                baseName = parts{end};
                dotParts = strsplit(baseName, '.');
                baseName = dotParts{1};
                phaseCalledNames{end+1} = baseName; %#ok<AGROW>
                if phaseCallCounts.isKey(baseName)
                    phaseCallCounts(baseName) = phaseCallCounts(baseName) + 1;
                else
                    phaseCallCounts(baseName) = 1;
                end
            end
        end
    end

    profilerFuncNames = unique(profilerFuncNames);
    phaseCalledNames  = unique(phaseCalledNames);

    % Compare against codebase
    calledMask = false(nFiles, 1);
    callCounts = zeros(nFiles, 1);

    for k = 1:nFiles
        fname = codebaseFuncs{k};
        % Check against full profiler data
        if any(strcmpi(profilerFuncNames, fname))
            calledMask(k) = true;
        end
        % Check phase-specific call count
        if phaseCallCounts.isKey(fname)
            callCounts(k) = phaseCallCounts(fname);
        elseif any(strcmpi(phaseCalledNames, fname))
            callCounts(k) = 1;
        end
    end

    calledFuncs   = codebaseFuncs(calledMask);
    uncalledFuncs = codebaseFuncs(~calledMask);
    uncalledFiles = codebaseFiles(~calledMask);

    if nFiles > 0
        coveragePct = 100 * sum(calledMask) / nFiles;
    else
        coveragePct = 0;
    end

    % Build a summary table
    calledStr = cell(nFiles, 1);
    for k = 1:nFiles
        if calledMask(k)
            calledStr{k} = 'Yes';
        else
            calledStr{k} = 'No';
        end
    end

    covTable = table(codebaseFuncs, codebaseFiles, calledStr, callCounts, ...
        'VariableNames', {'Name', 'File', 'Called', 'CallCount'});

    % Sort: uncalled first, then by name
    covTable = sortrows(covTable, {'Called', 'Name'}, {'ascend', 'ascend'});

    % Package output
    result.codebaseFunctions = codebaseFuncs;
    result.codebaseFiles     = codebaseFiles;
    result.calledFunctions   = calledFuncs;
    result.uncalledFunctions = uncalledFuncs;
    result.uncalledFiles     = uncalledFiles;
    result.coveragePercent   = coveragePct;
    result.coverageTable     = covTable;
end
