function result = parseProfilerPhases(matFile, startPhase, endPhase, options)
% PARSEPROFILERPHASES Load profiler .mat and extract call sequence for a phase range.
%
%   result = parseProfilerPhases(matFile, startPhase, endPhase)
%   result = parseProfilerPhases(matFile, startPhase, endPhase, options)
%
%   Inputs:
%     matFile    - Path to the profiler .mat file
%     startPhase - Starting phase number (1-indexed)
%     endPhase   - Ending phase number (1-indexed, inclusive)
%     options    - (optional) struct with fields:
%       .hideBuiltins    - logical, exclude Builtin type functions (default: false)
%       .hideMatlabroot  - logical, exclude functions under matlabroot (default: false)
%       .excludeNames    - cell array of function names to exclude (default: {})
%       .phaseFunction   - name of the phase boundary function (default: 'phase_iterator')
%
%   Output:
%     result - struct with fields:
%       .callSequence   - struct array with fields: index, funcName, fileName,
%                         funcType, depth, event ('enter'/'exit'), histRow
%       .phaseIndices   - row indices in FunctionHistory where phase_iterator is entered
%       .totalPhases    - total number of phases detected
%       .functionTable  - the original FunctionTable from the profiler
%       .rawHistory     - the raw FunctionHistory matrix
%       .startPhase     - the requested start phase
%       .endPhase       - the requested end phase

    if nargin < 4
        options = struct();
    end

    hideBuiltins   = getOpt(options, 'hideBuiltins', false);
    hideMatlabroot = getOpt(options, 'hideMatlabroot', false);
    excludeNames   = getOpt(options, 'excludeNames', {});
    phaseFuncName  = getOpt(options, 'phaseFunction', 'phase_iterator');

    % Load the .mat file
    data = load(matFile);

    % Find the profile_info struct - it may be top-level or nested
    if isfield(data, 'profile_info')
        pinfo = data.profile_info;
    else
        fnames = fieldnames(data);
        pinfo = [];
        for k = 1:numel(fnames)
            candidate = data.(fnames{k});
            if isstruct(candidate) && isfield(candidate, 'FunctionTable') ...
                    && isfield(candidate, 'FunctionHistory')
                pinfo = candidate;
                break;
            end
        end
        if isempty(pinfo)
            error('parseProfilerPhases:noProfileInfo', ...
                'Could not find profile_info with FunctionTable and FunctionHistory in the .mat file.');
        end
    end

    funcTable   = pinfo.FunctionTable;
    funcHistory = pinfo.FunctionHistory;

    % Build a map of function index -> name for quick lookup
    nFuncs = numel(funcTable);
    funcNames = cell(nFuncs, 1);
    for k = 1:nFuncs
        funcNames{k} = funcTable(k).FunctionName;
    end

    % Find the index of phase_iterator in FunctionTable
    phaseIdx = find(strcmpi(funcNames, phaseFuncName));
    if isempty(phaseIdx)
        % Try partial match on function name (e.g., path>phase_iterator)
        for k = 1:nFuncs
            parts = strsplit(funcNames{k}, '>');
            if any(strcmpi(parts, phaseFuncName))
                phaseIdx(end+1) = k; %#ok<AGROW>
            end
        end
    end
    if isempty(phaseIdx)
        error('parseProfilerPhases:noPhaseFunc', ...
            'Function "%s" not found in profiler data.', phaseFuncName);
    end

    % Find all rows where phase_iterator is entered (event == 0)
    isPhaseEnter = funcHistory(:,1) == 0 & ismember(funcHistory(:,2), phaseIdx);
    phaseRows = find(isPhaseEnter);
    totalPhases = numel(phaseRows);

    if totalPhases == 0
        error('parseProfilerPhases:noPhases', ...
            'No calls to "%s" found in FunctionHistory.', phaseFuncName);
    end

    % Validate requested range
    if startPhase < 1 || startPhase > totalPhases
        error('parseProfilerPhases:badRange', ...
            'startPhase %d is out of range [1, %d].', startPhase, totalPhases);
    end
    if endPhase < startPhase || endPhase > totalPhases
        error('parseProfilerPhases:badRange', ...
            'endPhase %d is out of range [%d, %d].', endPhase, startPhase, totalPhases);
    end

    % Determine the row range to extract
    rowStart = phaseRows(startPhase);
    if endPhase < totalPhases
        % Go up to (but not including) the next phase after endPhase
        rowEnd = phaseRows(endPhase + 1) - 1;
    else
        rowEnd = size(funcHistory, 1);
    end

    subHistory = funcHistory(rowStart:rowEnd, :);
    nRows = size(subHistory, 1);

    % Build the call sequence with depth tracking
    matlabRoot = matlabroot;
    depth = 0;
    callSeq = struct('index', {}, 'funcName', {}, 'fileName', {}, ...
                     'funcType', {}, 'depth', {}, 'event', {}, 'histRow', {});
    seqIdx = 0;

    for r = 1:nRows
        eventCode = subHistory(r, 1);
        fIdx      = subHistory(r, 2);

        if fIdx < 1 || fIdx > nFuncs
            continue;
        end

        fName = funcTable(fIdx).FunctionName;
        fFile = '';
        if isfield(funcTable, 'FileName')
            fFile = funcTable(fIdx).FileName;
        end
        fType = '';
        if isfield(funcTable, 'Type')
            fType = funcTable(fIdx).Type;
        end

        % Handle depth
        if eventCode == 0  % enter
            depth = depth + 1;
            eventStr = 'enter';
        else  % exit
            eventStr = 'exit';
        end

        % Apply filters
        skip = false;
        if hideBuiltins && strcmpi(fType, 'Builtin')
            skip = true;
        end
        if hideMatlabroot && ~isempty(fFile) && startsWith(fFile, matlabRoot)
            skip = true;
        end
        if ~isempty(excludeNames) && any(strcmpi(fName, excludeNames))
            skip = true;
        end

        if ~skip
            seqIdx = seqIdx + 1;
            callSeq(seqIdx).index    = seqIdx;
            callSeq(seqIdx).funcName = fName;
            callSeq(seqIdx).fileName = fFile;
            callSeq(seqIdx).funcType = fType;
            callSeq(seqIdx).depth    = depth;
            callSeq(seqIdx).event    = eventStr;
            callSeq(seqIdx).histRow  = rowStart + r - 1;
        end

        if eventCode == 1  % exit
            depth = max(depth - 1, 0);
        end
    end

    % Package output
    result.callSequence  = callSeq;
    result.phaseIndices  = phaseRows;
    result.totalPhases   = totalPhases;
    result.functionTable = funcTable;
    result.rawHistory    = funcHistory;
    result.startPhase    = startPhase;
    result.endPhase      = endPhase;
end

function val = getOpt(opts, fieldName, default)
    if isfield(opts, fieldName)
        val = opts.(fieldName);
    else
        val = default;
    end
end
